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

        # Filter 4: price must be rising but not already pumped
        price_change = (price_now - price_prev) / price_prev * 100
        if price_change < PRICE_CHANGE_MIN:
            continue
        if price_change > PRICE_CHANGE_MAX:
            continue

        volume_24h = rec.get("volume_24h", 0) or 0

        # Filter 5: minimum liquidity (24h volume)
        if volume_24h < VOLUME_24H_MIN:
            continue

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

        # Filter 5: OI must be growing (not contracting)
        if oi_change < OI_CHANGE_MIN:
            continue

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

    return signals
