import logging
import os
import time

from config import POLL_INTERVAL, LOOKBACK_MINUTES, DATA_DIR, SNAPSHOT_RETENTION_HOURS, OI_1H_MIN
from db import init_db, save_snapshots, get_snapshots_before, purge_old
from collector import collect_snapshot
from signal_engine import evaluate
from enrich import enrich
from alerter import send_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # иначе строка на каждый из ~500 символов

log = logging.getLogger(__name__)


def run_cycle():
    records = collect_snapshot()
    if not records:
        log.warning("Empty snapshot, skipping cycle")
        return

    now_ts = save_snapshots(records)
    prev_records = get_snapshots_before(now_ts, LOOKBACK_MINUTES * 60)

    if not prev_records:
        log.info("No historical data yet, accumulating...")
        return

    candidates = evaluate(records, prev_records)
    if candidates:
        # Enrich обязателен до фильтра: OI 1ч тянется с Binance внутри него.
        _enrich_signals(candidates, records, now_ts)
        signals = _filter_oi_1h(candidates)
        if signals:
            log.info(f"Sending {len(signals)} signal(s)")
            send_signals(signals)
    else:
        log.info("No signals this cycle")

    purge_old(older_than_seconds=int(SNAPSHOT_RETENTION_HOURS * 3600))


def _oi_map(records: list[dict]) -> dict:
    """(symbol, exchange) -> (oi_usdt, price).

    Цена нужна вместе с OI: `openInterest` у BingX — долларовый notional,
    и чтобы получить число монет, его надо делить на цену того же снапшота.
    """
    return {(r["symbol"], r["exchange"]): (r.get("oi"), r.get("price")) for r in records}


def _filter_oi_1h(candidates: list) -> list:
    """Фильтр по OI на горизонте 1ч. Заменил фильтр на 30м 2026-08-15.

    Стоит здесь, а не в `signal_engine`, потому что `oi_1h` появляется только
    после enrich (Binance `openInterestHist`, монеты).

    `oi_1h is None` пропускаем: у части монет OI недоступен ни с Binance, ни из
    снапшотов, а конкурент такие сигналы шлёт (OPENEDEN и DOS 14.08, оба тейк).
    Отсекать их значило бы молча потерять целый класс монет.
    """
    kept = []
    for sig in candidates:
        # OI 30м пишем в лог всегда, хотя фильтр по нему выключен: без этого
        # в сверке нельзя ответить «а срезал бы старый фильтр этот сигнал?».
        # 15-16.08 такой вопрос уже возник и данных не оказалось.
        oi30 = "н/д" if sig.oi_change_pct is None else f"{sig.oi_change_pct:+.2f}%"
        if sig.oi_1h is not None and sig.oi_1h <= OI_1H_MIN:
            log.info("Отсев: %s — OI 1ч %+.2f%% <= %.1f%% [цена %+.2f%%, OI 30м %s, OI 4ч %s]",
                     sig.symbol, sig.oi_1h, OI_1H_MIN, sig.price_change_pct, oi30,
                     "н/д" if sig.oi_4h is None else f"{sig.oi_4h:+.2f}%")
            continue
        log.info("Прошёл: %s — OI 1ч %s [цена %+.2f%%, OI 30м %s, OI 4ч %s]",
                 sig.symbol, "н/д" if sig.oi_1h is None else f"{sig.oi_1h:+.2f}%",
                 sig.price_change_pct, oi30,
                 "н/д" if sig.oi_4h is None else f"{sig.oi_4h:+.2f}%")
        kept.append(sig)
    log.info("Фильтр OI 1ч: кандидатов %d → сигналов %d", len(candidates), len(kept))
    return kept


def _enrich_signals(signals: list, records: list[dict], now_ts: int):
    """Дозаполнить сигналы контекстом (RSI, Л/Ш, OI 1ч/4ч, вердикт).

    Запросы идут только по символам сигналов — обычно единицы за цикл.
    """
    oi_now = _oi_map(records)
    oi_1h = _oi_map(get_snapshots_before(now_ts, 3600))
    oi_4h = _oi_map(get_snapshots_before(now_ts, 14400))
    for sig in signals:
        try:
            enrich(sig, oi_1h, oi_4h, oi_now)
        except Exception as e:
            log.warning(f"Enrich failed for {sig.symbol}: {e}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    init_db()
    log.info(f"Funding alerts bot started (poll={POLL_INTERVAL}s, lookback={LOOKBACK_MINUTES}m)")

    while True:
        started = time.monotonic()
        try:
            run_cycle()
        except Exception as e:
            log.exception(f"Cycle error: {e}")
        # Спим остаток интервала, а не полный: сбор снапшота теперь идёт в темпе
        # под лимит BingX и занимает ~80с вместо 13с. Со старым `sleep(POLL_INTERVAL)`
        # цикл растянулся бы до ~6.5 минут, а мы и так отстаём от конкурента.
        rest = POLL_INTERVAL - (time.monotonic() - started)
        if rest > 0:
            time.sleep(rest)
        else:
            log.warning(f"Цикл занял {time.monotonic() - started:.0f}с — дольше интервала")


if __name__ == "__main__":
    main()
