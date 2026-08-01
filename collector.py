import logging
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

BINGX_BASE = "https://open-api.bingx.com"
CLIENT = httpx.Client(timeout=15)


def _get(url: str, params: dict = None) -> list | dict:
    resp = CLIENT.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


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


def _bingx_funding_one(symbol: str) -> tuple[str, dict | None]:
    try:
        data = _get(
            f"{BINGX_BASE}/openApi/swap/v2/quote/premiumIndex",
            {"symbol": symbol},
        )["data"]
        return symbol, data
    except Exception as e:
        log.debug(f"BingX funding error {symbol}: {e}")
        return symbol, None


def _bingx_oi_one(symbol: str) -> tuple[str, float | None]:
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
            {"symbol": symbol},
        )["data"]
        return symbol, float(data["openInterest"])
    except Exception as e:
        log.debug(f"BingX OI error {symbol}: {e}")
        return symbol, None


def collect_snapshot() -> list[dict]:
    log.info("Collecting snapshot from BingX...")
    symbols, volume_map = _bingx_all_symbols()
    log.info(f"BingX: {len(symbols)} symbols")

    funding_map, prices, next_ft = {}, {}, {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_bingx_funding_one, s): s for s in symbols}
        for f in as_completed(futures):
            sym, data = f.result()
            if data:
                funding_map[sym] = round(float(data["lastFundingRate"]) * 100, 4)
                prices[sym] = float(data["markPrice"])
                next_ft[sym] = int(data["nextFundingTime"])

    oi_map = {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_bingx_oi_one, s): s for s in symbols}
        for f in as_completed(futures):
            sym, oi = f.result()
            if oi is not None:
                oi_map[sym] = oi

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
    log.info(f"BingX: {len(records)} records collected")
    return records
