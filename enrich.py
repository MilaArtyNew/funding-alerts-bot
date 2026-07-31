"""Дообогащение сигнала контекстом: RSI, лонг/шорт соотношение, ликвидации, вердикт.

Запрашивается только для символов, которые уже прошли фильтры сигнала (единицы за цикл),
поэтому лишней нагрузки на API нет.

Источники:
- RSI (15м / 1ч / 4ч) — BingX klines, публично
- Л/Ш 1ч — Binance globalLongShortAccountRatio, публично; на BingX такого эндпоинта нет.
  Тикеры бирж расходятся, поэтому для части монет данных не будет — тогда «н/д».
- Ликвидации 1ч — Coinglass, только при заданном COINGLASS_API_KEY (бесплатного источника нет)
"""
import logging

import httpx

from config import COINGLASS_API_KEY, OI_GROWTH_MIN, SHORT_SHARE_MIN

log = logging.getLogger(__name__)

BINGX_BASE = "https://open-api.bingx.com"
BINANCE_BASE = "https://fapi.binance.com"
BYBIT_BASE = "https://api.bybit.com"
COINGLASS_BASE = "https://open-api-v4.coinglass.com"

CLIENT = httpx.Client(timeout=10)

RSI_PERIOD = 14
_INTERVALS = (("15m", "15m"), ("1h", "1h"), ("4h", "4h"))


# ---------------------------------------------------------------------- #
#  RSI
# ---------------------------------------------------------------------- #

def calc_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """RSI по Уайлдеру. closes — от старых к новым."""
    if len(closes) < period + 1:
        return None

    gains = losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains += max(diff, 0.0)
        losses += max(-diff, 0.0)
    avg_gain, avg_loss = gains / period, losses / period

    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(diff, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-diff, 0.0)) / period

    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 0)


def _fetch_closes(symbol: str, interval: str, limit: int = 100) -> list[float]:
    """Цены закрытия от старых к новым. BingX отдаёт свечи от новых к старым."""
    resp = CLIENT.get(f"{BINGX_BASE}/openApi/swap/v3/quote/klines",
                      params={"symbol": symbol, "interval": interval, "limit": limit})
    resp.raise_for_status()
    data = resp.json().get("data") or []
    candles = sorted(data, key=lambda c: int(c["time"]))
    return [float(c["close"]) for c in candles]


def fetch_rsi(symbol: str) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for label, interval in _INTERVALS:
        try:
            out[label] = calc_rsi(_fetch_closes(symbol, interval))
        except Exception as e:
            log.debug(f"RSI {symbol} {interval}: {e}")
            out[label] = None
    return out


# ---------------------------------------------------------------------- #
#  Long / Short accounts
# ---------------------------------------------------------------------- #

def _ls_binance(flat_symbol: str) -> tuple[float, float] | None:
    resp = CLIENT.get(f"{BINANCE_BASE}/futures/data/globalLongShortAccountRatio",
                      params={"symbol": flat_symbol, "period": "1h", "limit": 1})
    if resp.status_code != 200:
        # 451 — Binance блокирует облачные/региональные IP. Важно видеть в логах,
        # иначе источник молча отваливается и вердикт превращается в «н/д».
        log.warning(f"L/S binance {flat_symbol}: HTTP {resp.status_code}")
        return None
    rows = resp.json()
    if not rows:
        return None
    row = rows[-1]
    return round(float(row["longAccount"]) * 100, 1), round(float(row["shortAccount"]) * 100, 1)


def _ls_bybit(flat_symbol: str) -> tuple[float, float] | None:
    resp = CLIENT.get(f"{BYBIT_BASE}/v5/market/account-ratio",
                      params={"category": "linear", "symbol": flat_symbol,
                              "period": "1h", "limit": 1})
    if resp.status_code != 200:
        log.warning(f"L/S bybit {flat_symbol}: HTTP {resp.status_code}")
        return None
    rows = ((resp.json() or {}).get("result") or {}).get("list") or []
    if not rows:
        return None
    row = rows[0]
    return round(float(row["buyRatio"]) * 100, 1), round(float(row["sellRatio"]) * 100, 1)


def fetch_long_short(symbol: str) -> tuple[float, float] | None:
    """(long %, short %) по счетам за 1ч.

    Binance основной, Bybit запасной: у Binance шире покрытие мелких монет, но он
    отдаёт 451 с части облачных IP. None — только если оба источника не ответили.
    """
    flat = symbol.replace("-", "")
    for name, fn in (("binance", _ls_binance), ("bybit", _ls_bybit)):
        try:
            res = fn(flat)
            if res:
                log.info(f"L/S {symbol}: {res[0]}%/{res[1]}% ({name})")
                return res
        except Exception as e:
            log.warning(f"L/S {name} {symbol}: {e}")
    log.warning(f"L/S {symbol}: нет данных ни у Binance, ни у Bybit")
    return None


# ---------------------------------------------------------------------- #
#  Liquidations (опционально — нужен платный ключ Coinglass)
# ---------------------------------------------------------------------- #

def fetch_liquidations(symbol: str) -> tuple[float, float] | None:
    """(шорты $, лонги $) ликвидированы за 1ч. None — если ключа нет или данных нет."""
    if not COINGLASS_API_KEY:
        return None
    try:
        resp = CLIENT.get(
            f"{COINGLASS_BASE}/api/futures/liquidation/history",
            params={"exchange": "BingX", "symbol": symbol, "interval": "1h", "limit": 1},
            headers={"CG-API-KEY": COINGLASS_API_KEY},
        )
        rows = (resp.json() or {}).get("data") or []
        if not rows:
            return None
        row = rows[-1]
        shorts = float(row.get("short_liquidation_usd") or row.get("shortLiquidationUsd") or 0)
        longs = float(row.get("long_liquidation_usd") or row.get("longLiquidationUsd") or 0)
        return shorts, longs
    except Exception as e:
        log.debug(f"Liquidations {symbol}: {e}")
        return None


# ---------------------------------------------------------------------- #
#  Вердикт
# ---------------------------------------------------------------------- #

def verdict(sig) -> tuple[str, str, float]:
    """(emoji, label, score) — сколько из трёх условий выполнено.

    Правило восстановлено по 10 сигналам конкурента (совпадение 10/10, см. README):
    ВХОД = OI растёт И на 1ч, И на 4ч, И толпа не в лонге (шортов ≥ SHORT_SHARE_MIN).

    Смысл: позиции набираются на обоих горизонтах, а шорты есть кому ликвидировать.
    RSI и ликвидации на вердикт не влияют — по ним правило не сходится (7/10 и 5/10
    промахов), они остаются справочными.
    """
    if sig.oi_1h is None or sig.oi_4h is None:
        return "▫️", "н/д", 0.0   # без OI правило не считается вообще

    checks = [sig.oi_1h >= OI_GROWTH_MIN, sig.oi_4h >= OI_GROWTH_MIN]
    if sig.ls_short is None:
        # Л/Ш не достали — решаем по двум условиям из трёх и помечаем неполноту,
        # чтобы сигнал не оставался без вердикта из-за отвалившегося источника
        sig.verdict_partial = True
    else:
        checks.append(sig.ls_short >= SHORT_SHARE_MIN)

    score = float(sum(checks))
    if all(checks):
        return "🟢", "ВХОД", score
    return "🟡", "СЛАБЫЙ", score


def enrich(sig, oi_1h_map: dict, oi_4h_map: dict, oi_now_map: dict):
    """Дозаполнить сигнал контекстом. Мутирует sig на месте."""
    key = (sig.symbol, sig.exchange)

    oi_now = oi_now_map.get(key)
    for label, src, attr in (("1h", oi_1h_map, "oi_1h"), ("4h", oi_4h_map, "oi_4h")):
        old = src.get(key)
        if oi_now and old:
            setattr(sig, attr, round((oi_now - old) / old * 100, 1))

    rsi = fetch_rsi(sig.symbol)
    sig.rsi_15m, sig.rsi_1h, sig.rsi_4h = rsi.get("15m"), rsi.get("1h"), rsi.get("4h")

    ls = fetch_long_short(sig.symbol)
    if ls:
        sig.ls_long, sig.ls_short = ls

    liq = fetch_liquidations(sig.symbol)
    if liq:
        sig.liq_short, sig.liq_long = liq

    sig.verdict_emoji, sig.verdict, sig.verdict_score = verdict(sig)
    return sig
