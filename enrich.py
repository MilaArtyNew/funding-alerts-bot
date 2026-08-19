"""Дообогащение сигнала контекстом: RSI, лонг/шорт соотношение, ликвидации, вердикт.

Запрашивается только для символов, которые уже прошли фильтры сигнала (единицы за цикл),
поэтому лишней нагрузки на API нет.

Источники:
- RSI (15м / 1ч / 4ч / 1д) — BingX klines, публично; если BingX отдал меньше 15 свечей
  (монета там листнута недавно), берём тот же интервал с Binance — иначе RSI «н/д»
- Л/Ш 1ч — Binance globalLongShortAccountRatio, публично; на BingX такого эндпоинта нет.
  Тикеры бирж расходятся, поэтому для части монет данных не будет — тогда «н/д».
- Ликвидации 1ч — Coinglass, только при заданном COINGLASS_API_KEY (бесплатного источника нет)
"""
import logging

import httpx

from config import (COINGLASS_API_KEY, OI_EDGE_PP, OI_GROWTH_MIN,
                    SHORT_SHARE_MIN, RSI_1D_MAX, VERDICT_USE_OI_1H)

log = logging.getLogger(__name__)

BINGX_BASE = "https://open-api.bingx.com"
BINANCE_BASE = "https://fapi.binance.com"
BYBIT_BASE = "https://api.bybit.com"
COINGLASS_BASE = "https://open-api-v4.coinglass.com"

CLIENT = httpx.Client(timeout=10)

RSI_PERIOD = 14
# 1д добавлен 2026-08-17: разбор шести сигналов конкурента 16-17.08 показал, что
# вердикт у него гасит именно дневной RSI, а не 4ч. CAP их различает: 4ч 62 при
# 1д 78 → у него СЛАБЫЙ. Пока поля не было, гипотезу нельзя было ни проверить,
# ни применить. На вердикт наш RSI по-прежнему не влияет — только в сообщение.
_INTERVALS = (("15m", "15m"), ("1h", "1h"), ("4h", "4h"), ("1d", "1d"))


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


def _closes_bingx(symbol: str, interval: str, limit: int = 100) -> list[float]:
    """Цены закрытия от старых к новым. BingX отдаёт свечи от новых к старым."""
    resp = CLIENT.get(f"{BINGX_BASE}/openApi/swap/v3/quote/klines",
                      params={"symbol": symbol, "interval": interval, "limit": limit})
    resp.raise_for_status()
    data = resp.json().get("data") or []
    candles = sorted(data, key=lambda c: int(c["time"]))
    return [float(c["close"]) for c in candles]


def _closes_binance(flat_symbol: str, interval: str, limit: int = 100) -> list[float]:
    """То же с Binance. Свечи уже от старых к новым, close — индекс 4."""
    resp = CLIENT.get(f"{BINANCE_BASE}/fapi/v1/klines",
                      params={"symbol": flat_symbol, "interval": interval, "limit": limit})
    resp.raise_for_status()
    return [float(c[4]) for c in resp.json()]


def _fetch_closes(symbol: str, interval: str, limit: int = 100) -> list[float]:
    """Свечи с BingX, а если истории не хватает на RSI — с Binance.

    2026-08-19: BingX отдаёт по BMT-USDT всего **9 дневных свечей** (монета там
    листнута ~9 дней назад), а RSI(14) требует 15. Из-за этого все четыре
    сигнала по BMT ушли с `RSI 1д: н/д`, тогда как у конкурента там 51 — на
    Binance та же монета торгуется дольше и отдаёт 100 свечей.

    Fallback безопасен: RSI одной и той же монеты на двух биржах практически
    совпадает — цены идут вместе, а RSI считается по их приращениям. Если монеты
    на Binance нет (REDSTONE, CASHCAT), запрос падает и мы честно оставляем «н/д»,
    как и раньше.
    """
    closes = []
    try:
        closes = _closes_bingx(symbol, interval, limit)
    except Exception as e:
        log.debug(f"klines BingX {symbol} {interval}: {e}")

    if len(closes) >= RSI_PERIOD + 1:
        return closes

    flat = symbol.replace("-", "")
    binance = _closes_binance(flat, interval, limit)
    log.info(f"RSI {symbol} {interval}: BingX дал {len(closes)} свечей "
             f"(нужно {RSI_PERIOD + 1}) → взяли {len(binance)} с Binance")
    return binance


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
#  Интервал выплаты фандинга
# ---------------------------------------------------------------------- #

def fetch_funding_interval(symbol: str) -> float | None:
    """Интервал выплаты фандинга в часах — по двум последним фактическим выплатам.

    По одному `next_funding_time` интервал не восстановить, а alerter раньше угадывал
    его по остатку времени и врал: монета с 4ч интервалом за 46м до выплаты
    помечалась как «(1h)». Настоящий 1ч интервал на BingX у единиц монет из ~545,
    так что догадка ошибалась систематически и испортила разбор статистики 01.08.
    """
    try:
        resp = CLIENT.get(f"{BINGX_BASE}/openApi/swap/v2/quote/fundingRate",
                          params={"symbol": symbol, "limit": 2})
        rows = (resp.json() or {}).get("data") or []
        if len(rows) < 2:
            return None
        times = sorted(int(r["fundingTime"]) for r in rows)
        hours = (times[1] - times[0]) / 3_600_000
        return round(hours, 2) if hours > 0 else None
    except Exception as e:
        log.debug(f"Funding interval {symbol}: {e}")
        return None


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
#  Open Interest
# ---------------------------------------------------------------------- #

def fetch_oi_binance(symbol: str) -> tuple[float, float] | None:
    """(изменение OI за 1ч %, за 4ч %) по числу монет, с Binance.

    Почему не BingX: поле `openInterest` у BingX — долларовый notional
    (`монеты × цена`), а истории OI у BingX нет вообще (`openInterestHist`
    отвечает code=100400). Конкурент считает монеты — его цифры совпадают
    с `sumOpenInterest` Binance с точностью 0.4 п.п. на 8 общих сигналах,
    наши долларовые мимо на 24 п.п. (разбор 12.08).

    Пересчёт истории по 71 закрытой сделке: `OI 4ч > 0` разделяет выборку
    на +0.07$ и −0.64$ на сделку, тогда как старый вердикт на долларовом OI
    давал −0.09$ против −0.31$.

    None — монеты нет на Binance (19% нашего юниверса) или мало истории.
    """
    flat = symbol.replace("-", "")
    try:
        resp = CLIENT.get(f"{BINANCE_BASE}/futures/data/openInterestHist",
                          params={"symbol": flat, "period": "5m", "limit": 60})
        if resp.status_code != 200:
            log.info(f"OI binance {flat}: HTTP {resp.status_code}")
            return None
        rows = resp.json()
    except Exception as e:
        log.warning(f"OI binance {flat}: {e}")
        return None
    if not isinstance(rows, list) or len(rows) < 50:
        return None

    pts = sorted((int(r["timestamp"]), float(r["sumOpenInterest"])) for r in rows)
    now_ms = pts[-1][0]

    def at(ms_ago: int) -> float | None:
        target = now_ms - ms_ago
        # допуск 15 мин: period=5m, отдельные точки у Binance выпадают
        older = [p for p in pts if p[0] <= target and target - p[0] <= 900_000]
        return older[-1][1] if older else None

    cur = pts[-1][1]
    h1, h4 = at(3_600_000), at(14_400_000)
    if not (cur and h1 and h4):
        return None
    return round((cur - h1) / h1 * 100, 1), round((cur - h4) / h4 * 100, 1)


# ---------------------------------------------------------------------- #
#  Вердикт
# ---------------------------------------------------------------------- #

def verdict(sig) -> tuple[str, str, float]:
    """(emoji, label, score) — сколько из трёх условий выполнено.

    ВХОД = OI 4ч растёт И толпа не в лонге (шортов ≥ SHORT_SHARE_MIN)
           И рынок не перегрет на дне (RSI 1д < RSI_1D_MAX).

    Смысл: позиции набираются на длинном горизонте, шорты есть кому ликвидировать,
    и монета не на вершине дневного движения — на перегретой мы покупаем у выхода.

    Переписано 2026-08-17 по 6 сигналам конкурента за 16-17.08 (объясняет 6/6,
    прежнее правило давало 2/5). Подробности и откат — в `config.py`.

    Побочно выставляет `sig.verdict_edge` — вердикт держится на значении OI 4ч,
    которое меньше расхождения между источниками OI (замер 18.08).
    Ликвидации и RSI 15м/1ч/4ч на вердикт не влияют — по ним правило не сходится.
    """
    if sig.oi_4h is None:
        return "▫️", "н/д", 0.0   # без OI 4ч правило не считается вообще

    checks = [sig.oi_4h >= OI_GROWTH_MIN]
    if VERDICT_USE_OI_1H:
        # Откат к правилу до 2026-08-17. None здесь = провал условия: раньше такой
        # сигнал вообще не получал вердикта, так что мягче трактовать нельзя.
        checks.append(sig.oi_1h is not None and sig.oi_1h >= OI_GROWTH_MIN)
    if sig.rsi_1d is None:
        # Источник отвалился — решаем по остальным условиям, как и с Л/Ш.
        # Сигналы до 2026-08-17 дневного RSI не имеют вовсе.
        sig.verdict_partial = True
    else:
        checks.append(sig.rsi_1d < RSI_1D_MAX)
    if sig.ls_short is None:
        # Л/Ш не достали — решаем по оставшимся условиям и помечаем неполноту,
        # чтобы сигнал не оставался без вердикта из-за отвалившегося источника
        sig.verdict_partial = True
    else:
        checks.append(sig.ls_short >= SHORT_SHARE_MIN)

    score = float(sum(checks))
    passed = all(checks)

    # «На грани»: OI 4ч ближе к порогу, чем типичное расхождение двух источников
    # (медиана 0.63 п.п., замер 18.08 — см. config.OI_EDGE_PP). Помечаем только
    # если от переворота этого условия МЕНЯЕТСЯ САМ ВЕРДИКТ: когда сигнал и так
    # СЛАБЫЙ из-за RSI или Л/Ш, шум в OI ничего не решает и пугать незачем.
    if OI_EDGE_PP and abs(sig.oi_4h - OI_GROWTH_MIN) < OI_EDGE_PP:
        flipped = [not checks[0]] + checks[1:]
        if all(flipped) != passed:
            sig.verdict_edge = True

    if passed:
        return "🟢", "ВХОД", score
    return "🟡", "СЛАБЫЙ", score


def _oi_from_snapshots(sig, oi_1h_map: dict, oi_4h_map: dict, oi_now_map: dict) -> bool:
    """Запасной путь: OI из наших снапшотов BingX, пересчитанный в МОНЕТЫ.

    В картах лежит `(oi_usdt, price)`. Делим одно на другое — получаем монеты.
    Метрика не идентична биржевой (BingX против Binance расходятся в среднем
    на 7.7 п.п.), поэтому источник помечается в `sig.oi_source`.
    """
    key = (sig.symbol, sig.exchange)
    now = oi_now_map.get(key)
    if not now or not now[0] or not now[1]:
        return False
    coins_now = now[0] / now[1]
    ok = False
    for src, attr in ((oi_1h_map, "oi_1h"), (oi_4h_map, "oi_4h")):
        old = src.get(key)
        if not old or not old[0] or not old[1]:
            continue
        coins_old = old[0] / old[1]
        if coins_old:
            setattr(sig, attr, round((coins_now - coins_old) / coins_old * 100, 1))
            ok = True
    return ok


def enrich(sig, oi_1h_map: dict, oi_4h_map: dict, oi_now_map: dict):
    """Дозаполнить сигнал контекстом. Мутирует sig на месте."""
    # OI: Binance основной (там монеты и есть история), наши снапшоты запасной.
    # Смешивать два источника под одним порогом опасно — это ровно тот класс
    # ошибки, который нашли 12.08, — поэтому источник пишется в sig.oi_source.
    oi = fetch_oi_binance(sig.symbol)
    if oi:
        sig.oi_1h, sig.oi_4h = oi
        sig.oi_source = "binance"
    elif _oi_from_snapshots(sig, oi_1h_map, oi_4h_map, oi_now_map):
        sig.oi_source = "bingx"
        log.info(f"OI {sig.symbol}: монеты нет на Binance, считаем по снапшотам BingX")

    sig.funding_interval_h = fetch_funding_interval(sig.symbol)

    rsi = fetch_rsi(sig.symbol)
    sig.rsi_15m, sig.rsi_1h, sig.rsi_4h = rsi.get("15m"), rsi.get("1h"), rsi.get("4h")
    sig.rsi_1d = rsi.get("1d")

    ls = fetch_long_short(sig.symbol)
    if ls:
        sig.ls_long, sig.ls_short = ls

    liq = fetch_liquidations(sig.symbol)
    if liq:
        sig.liq_short, sig.liq_long = liq

    sig.verdict_emoji, sig.verdict, sig.verdict_score = verdict(sig)
    return sig
