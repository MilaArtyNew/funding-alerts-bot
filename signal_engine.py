import logging
from dataclasses import dataclass
from config import FUNDING_THRESHOLD, FUNDING_DELTA_MIN, PRICE_CHANGE_MIN, PRICE_CHANGE_MAX, OI_CHANGE_MIN, VOLUME_24H_MIN, SHORT_LIQ_MIN

log = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    exchange: str
    funding_prev: float
    funding_now: float
    funding_delta: float       # funding_now - funding_prev
    price_prev: float
    price_now: float
    price_change_pct: float
    oi_change_pct: float
    short_liq: float
    next_funding_time: int     # ms timestamp
    strong: bool

    # Контекст, дозаполняется в enrich.py уже после отбора сигнала.
    # None = данные недоступны (нет источника / монеты нет на Binance / мало истории)
    rsi_15m: float | None = None
    rsi_1h: float | None = None
    rsi_4h: float | None = None
    ls_long: float | None = None    # % счетов в лонге за 1ч
    ls_short: float | None = None   # % счетов в шорте за 1ч
    oi_1h: float | None = None      # изменение OI за 1ч, % (в монетах, не в $)
    oi_4h: float | None = None      # изменение OI за 4ч, % (в монетах, не в $)
    oi_source: str | None = None    # "binance" | "bingx" — откуда взят OI 1ч/4ч
    liq_short: float | None = None  # ликвидировано шортов за 1ч, $
    liq_long: float | None = None   # ликвидировано лонгов за 1ч, $
    funding_interval_h: float | None = None  # настоящий интервал выплаты, ч (не догадка)
    verdict: str = "СЛАБЫЙ"
    verdict_emoji: str = "🟡"
    verdict_score: float = 0.0
    verdict_partial: bool = False   # вердикт посчитан без Л/Ш (источник не ответил)


def evaluate(current: list[dict], previous: list[dict]) -> list[Signal]:
    prev_map = {(r["symbol"], r["exchange"]): r for r in previous}
    signals = []

    # Причина отсева по символу. Без неё разбор расхождений с конкурентом упирается
    # в то, что снапшоты живут 5 часов и задним числом уже ничего не восстановить
    # (сверка 13.08: из 12 его сигналов один остался необъяснённым).
    # Пишем подробно только про тех, кто прошёл фандинговые фильтры — таких
    # единицы за цикл, остальные 560 символов отсеиваются на первом же условии.
    funnel = {"пар": 0, "фандинг": 0, "цена": 0, "объём": 0, "OI 30м": 0}
    near: list[str] = []

    def отсев(symbol, причина, rec_price, fp, fn):
        near.append(f"{symbol} — {причина} [цена {rec_price:+.2f}%, "
                    f"фандинг {fp:+.3f}→{fn:+.3f}%]")

    for rec in current:
        symbol = rec["symbol"]
        exchange = rec["exchange"]
        prev = prev_map.get((symbol, exchange))
        if not prev:
            continue

        funding_now = rec.get("funding_rate")
        price_now = rec.get("price")
        oi_now = rec.get("oi")
        short_liq = rec.get("short_liq", 0) or 0
        next_ft = rec.get("next_funding_time", 0) or 0

        funding_prev = prev.get("funding_rate")
        price_prev = prev.get("price")
        oi_prev = prev.get("oi")

        if any(v is None for v in [funding_now, price_now, funding_prev, price_prev]):
            continue
        if price_prev == 0:
            continue

        funnel["пар"] += 1

        # Filter 1: 30m ago funding was at/above threshold (fresh crossing only)
        if funding_prev < FUNDING_THRESHOLD:
            continue

        # Filter 2: now funding is at/below threshold
        if funding_now > FUNDING_THRESHOLD:
            continue

        funding_delta = funding_now - funding_prev

        # Filter 3: funding must be getting more negative (not static or float micro-noise)
        if funding_delta >= 0:
            continue
        if funding_delta > FUNDING_DELTA_MIN:
            continue

        funnel["фандинг"] += 1
        price_change = (price_now - price_prev) / price_prev * 100

        # Filter 4: price must be rising but not already pumped
        if price_change < PRICE_CHANGE_MIN:
            отсев(symbol, f"цена {price_change:+.2f}% < {PRICE_CHANGE_MIN}%",
                  price_change, funding_prev, funding_now)
            continue
        if price_change > PRICE_CHANGE_MAX:
            отсев(symbol, f"цена {price_change:+.2f}% > {PRICE_CHANGE_MAX}%",
                  price_change, funding_prev, funding_now)
            continue

        funnel["цена"] += 1
        volume_24h = rec.get("volume_24h", 0) or 0

        # Filter 5: minimum liquidity (24h volume)
        if volume_24h < VOLUME_24H_MIN:
            отсев(symbol, f"объём 24ч {volume_24h:,.0f}$ < {VOLUME_24H_MIN:,.0f}$",
                  price_change, funding_prev, funding_now)
            continue

        funnel["объём"] += 1

        # OI считаем В МОНЕТАХ, а не в долларах. Поле `openInterest` у BingX —
        # долларовый notional, то есть `монеты × цена`. Сигнал мы выдаём только
        # на растущей цене, поэтому долларовый OI рос почти всегда сам собой:
        # условие «OI растёт» было истинно у 83% наших сигналов против 48% у
        # конкурента (разбор 12.08). Делим на цену — получаем число монет.
        oi_change = 0.0
        if oi_prev and oi_now and price_prev and price_now:
            coins_prev = oi_prev / price_prev
            coins_now = oi_now / price_now
            if coins_prev:
                oi_change = (coins_now - coins_prev) / coins_prev * 100

        # Filter 6: OI за 30м. По умолчанию выключен (OI_CHANGE_MIN = -100) —
        # фильтр по OI перенесён на горизонт 1ч и живёт в main._filter_oi_1h,
        # см. комментарий в config.py. Здесь остался как путь отката через env.
        if oi_change < OI_CHANGE_MIN:
            отсев(symbol, f"OI 30м {oi_change:+.2f}% < {OI_CHANGE_MIN}% (в монетах)",
                  price_change, funding_prev, funding_now)
            continue

        funnel["OI 30м"] += 1
        strong = short_liq >= SHORT_LIQ_MIN

        signals.append(Signal(
            symbol=symbol,
            exchange=exchange,
            funding_prev=funding_prev,
            funding_now=funding_now,
            funding_delta=funding_delta,
            price_prev=price_prev,
            price_now=price_now,
            price_change_pct=price_change,
            oi_change_pct=oi_change,
            short_liq=short_liq,
            next_funding_time=next_ft,
            strong=strong,
        ))
        log.info(
            f"Signal: [{exchange}] {symbol} funding={funding_now:+.4f}% "
            f"(Δ{funding_delta:+.4f}%) price={price_change:+.2f}%"
        )

    log.info("Воронка: пар %d → фандинг %d → цена %d → объём %d → OI 30м %d → кандидатов %d",
             funnel["пар"], funnel["фандинг"], funnel["цена"],
             funnel["объём"], funnel["OI 30м"], len(signals))
    for line in near:
        log.info("Отсев: %s", line)

    return signals
