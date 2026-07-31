import logging
import os
import time

from config import POLL_INTERVAL, LOOKBACK_MINUTES, DATA_DIR, SNAPSHOT_RETENTION_HOURS
from db import init_db, save_snapshots, get_snapshots_before, purge_old
from collector import collect_snapshot
from signal_engine import evaluate
from enrich import enrich
from alerter import send_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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

    signals = evaluate(records, prev_records)
    if signals:
        log.info(f"Sending {len(signals)} signal(s)")
        _enrich_signals(signals, records, now_ts)
        send_signals(signals)
    else:
        log.info("No signals this cycle")

    purge_old(older_than_seconds=int(SNAPSHOT_RETENTION_HOURS * 3600))


def _oi_map(records: list[dict]) -> dict:
    return {(r["symbol"], r["exchange"]): r.get("oi") for r in records}


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
        try:
            run_cycle()
        except Exception as e:
            log.exception(f"Cycle error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
