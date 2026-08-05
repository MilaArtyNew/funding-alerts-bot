import logging
import os
import threading
import time
import httpx
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

BINGX_BASE = "https://open-api.bingx.com"
CLIENT = httpx.Client(timeout=15)

RATE_LIMIT_CODE = 100410   # "The endpoint trigger frequency..." — лимит частоты, не объёма

# Раньше коллектор выпускал 1102 запроса (551 premiumIndex + 551 openInterest)
# в 20 потоков за ~13 секунд и сам себе выбивал лимит BingX: последние ~51 монета
# получала 100410 и не попадала в снапшот ВООБЩЕ — одни и те же 500 символов
# во всех 58 циклах подряд. В слепой зоне сидели DYM (39M$ оборота), HOME (16.8M$),
# ETHFI (13.3M$). Ошибки при этом молчали в log.debug, в логе было ровное
# "500 records collected", и потеря 9% рынка выглядела нормой.
#
# Измерено 2026-08-05: при молчании квота восстанавливается за 61 секунду, все
# «потерянные» монеты отвечают code=0, а первый цикл на свежей квоте собрал 551/551.
# Значит лечится темпом: запросы размазываются во времени вместо залпа.
REQUESTS_PER_SEC = float(os.environ.get("BINGX_RPS", "7"))
WORKERS = int(os.environ.get("BINGX_WORKERS", "20"))


class _Throttle:
    """Не чаще `rps` запросов в секунду на эндпоинт.

    У каждого эндпоинта свой счётчик на стороне BingX, поэтому и здесь свой
    экземпляр — иначе два прохода делили бы один темп и цикл растянулся бы вдвое.
    """

    def __init__(self, rps: float):
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        if not self._interval:
            return
        with self._lock:
            target = max(time.monotonic(), self._next)
            self._next = target + self._interval
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def _get(url: str, params: dict = None, throttle: "_Throttle" = None,
         attempts: int = 3) -> list | dict:
    """GET с учётом темпа и повтором на лимите частоты.

    BingX отдаёт лимит кодом 100410 внутри HTTP 200, поэтому raise_for_status
    его не ловит — проверяем тело ответа.
    """
    last_error = None
    for attempt in range(attempts):
        if throttle:
            throttle.wait()
        try:
            resp = CLIENT.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            last_error = e
            time.sleep(0.5 * (attempt + 1))
            continue

        code = data.get("code") if isinstance(data, dict) else 0
        if code in (0, None):
            return data

        last_error = RuntimeError(f"BingX code={code}: {data.get('msg', '')}")
        if code != RATE_LIMIT_CODE:
            break
        time.sleep(1.5 * (attempt + 1))   # лимит частотный — помогает только пауза

    raise last_error


def _bingx_all_symbols() -> tuple[list[str], dict[str, float]]:
    """Returns (symbols, volume_map) — volume in USDT 24h from ticker."""
    data = _get(f"{BINGX_BASE}/openApi/swap/v2/quote/ticker")["data"]
    symbols, volume_map = [], {}
    for d in data:
        sym = d["symbol"]
        if not sym.endswith("-USDT") or "2USD" in sym:
            continue
        symbols.append(sym)
        try:
            volume_map[sym] = float(d.get("quoteVolume") or 0)
        except (ValueError, TypeError):
            volume_map[sym] = 0.0
    return symbols, volume_map


def _bingx_funding_one(symbol: str, throttle: _Throttle = None) -> tuple[str, dict | None]:
    try:
        data = _get(
            f"{BINGX_BASE}/openApi/swap/v2/quote/premiumIndex",
            {"symbol": symbol}, throttle,
        )["data"]
        return symbol, data
    except Exception as e:
        log.debug(f"BingX funding error {symbol}: {e}")
        return symbol, None


def _bingx_oi_one(symbol: str, throttle: _Throttle = None) -> tuple[str, float | None]:
    """Открытый интерес как его отдаёт BingX — уже в USDT, умножать на цену не надо.

    Раньше здесь было `* price`. Поле и так номинировано в долларах (BTC-USDT
    отдаёт ~7.8e8 при цене 63k — как монеты это было бы больше всей эмиссии),
    так что старое значение было в бессмысленных единицах, а рост OI за 1ч/4ч
    дополнительно включал в себя рост цены. Сигнал мы даём только на растущей цене,
    поэтому OI почти всегда выходил положительным и вердикт ВХОД срабатывал вхолостую.
    Проверено на 4 сигналах: расхождение с конкурентом в точности равно росту цены
    за тот же час.
    """
    try:
        data = _get(
            f"{BINGX_BASE}/openApi/swap/v2/quote/openInterest",
            {"symbol": symbol}, throttle,
        )["data"]
        return symbol, float(data["openInterest"])
    except Exception as e:
        log.debug(f"BingX OI error {symbol}: {e}")
        return symbol, None


def _fetch_all(symbols: list[str], worker, label: str) -> dict:
    """Опросить все символы в заданном темпе и добрать не ответивших вторым проходом.

    Второй проход последовательный: не ответивших единицы, а после залпа лимит
    как раз и нужно дать отпустить.
    """
    throttle = _Throttle(REQUESTS_PER_SEC)
    out = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for sym, val in pool.map(lambda s: worker(s, throttle), symbols):
            if val is not None:
                out[sym] = val

    missing = [s for s in symbols if s not in out]
    if missing:
        log.info(f"BingX {label}: добираем {len(missing)} не ответивших")
        time.sleep(2)
        for s in missing:
            sym, val = worker(s, throttle)
            if val is not None:
                out[sym] = val

    lost = [s for s in symbols if s not in out]
    if lost:
        log.warning(
            f"BingX {label}: потеряно {len(lost)} символов из {len(symbols)} — "
            f"{', '.join(lost[:8])}{'...' if len(lost) > 8 else ''}"
        )
    return out


def collect_snapshot() -> list[dict]:
    log.info("Collecting snapshot from BingX...")
    symbols, volume_map = _bingx_all_symbols()
    log.info(f"BingX: {len(symbols)} symbols")

    # Два эндпоинта — два независимых счётчика лимита на стороне BingX, поэтому
    # проходы идут параллельно: последовательно цикл занял бы вдвое больше времени
    # и отставание от конкурента (и так 10–86 минут) выросло бы ещё.
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as outer:
        f_funding = outer.submit(_fetch_all, symbols, _bingx_funding_one, "funding")
        f_oi = outer.submit(_fetch_all, symbols, _bingx_oi_one, "OI")
        raw_funding = f_funding.result()
        oi_map = f_oi.result()

    funding_map, prices, next_ft = {}, {}, {}
    for sym, data in raw_funding.items():
        try:
            funding_map[sym] = round(float(data["lastFundingRate"]) * 100, 4)
            prices[sym] = float(data["markPrice"])
            next_ft[sym] = int(data["nextFundingTime"])
        except (KeyError, ValueError, TypeError) as e:
            log.debug(f"BingX funding parse {sym}: {e}")

    records = []
    for sym in symbols:
        if sym not in funding_map:
            continue
        records.append({
            "symbol": sym,
            "exchange": "BingX",
            "funding_rate": funding_map.get(sym),
            "price": prices.get(sym),
            "oi": oi_map.get(sym),
            "short_liq": 0.0,
            "next_funding_time": next_ft.get(sym, 0),
            "volume_24h": volume_map.get(sym, 0.0),
        })
    elapsed = time.monotonic() - started
    if len(records) < len(symbols):
        log.warning(
            f"BingX: {len(records)} records из {len(symbols)} символов "
            f"за {elapsed:.0f}с — {len(symbols) - len(records)} монет не попали в снапшот"
        )
    else:
        log.info(f"BingX: {len(records)} records collected за {elapsed:.0f}с")
    return records
