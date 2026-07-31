import time
import httpx
import logging
from datetime import datetime, timedelta
from signal_engine import Signal
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, COOLDOWN_MINUTES
from trade_webhook import send_trade_signal

log = logging.getLogger(__name__)

TG_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
_cooldown: dict[tuple[str, str], datetime] = {}


def _fmt_liq(usd: float) -> str:
    if usd >= 1_000_000:
        return f"${usd/1_000_000:.1f}M"
    if usd >= 1_000:
        return f"${usd/1_000:.0f}k"
    return f"${usd:.0f}"


def _fmt_funding_count(next_funding_time_ms: int) -> str:
    if not next_funding_time_ms:
        return "—"
    minutes_left = max(0, (next_funding_time_ms / 1000 - time.time()) / 60)
    # guess interval from minutes_left
    if minutes_left <= 65:
        interval = "1h"
    elif minutes_left <= 260:
        interval = "4h"
    else:
        interval = "8h"
    return f"{int(minutes_left)}m ({interval})"


def _chart_url(sig: Signal) -> str:
    base = sig.symbol.replace("-USDT", "")
    return f"https://www.tradingview.com/chart/?symbol=BINGX:{base}-USDT"


def _fmt_pct(value: float | None) -> str:
    return "н/д" if value is None else f"{value:+.1f}%"


def _fmt_rsi(value: float | None) -> str:
    return "н/д" if value is None else f"{value:.0f}"


def format_message(sig: Signal) -> str:
    header = "🔥 Strong signal" if sig.strong else "🟢 Long setup"
    trend = "углубляется" if sig.funding_delta < 0 else "растёт"
    funding_count = _fmt_funding_count(sig.next_funding_time)

    lines = [
        f"{header} — {sig.symbol}",
        "",
        f"⚙️ Фандинг 30м: {sig.funding_prev:+.2f}% → {sig.funding_now:+.2f}% ({trend})",
        f"⏱️ Выплата фандинга через {funding_count}",
        f"💹 Цена за 30м: {sig.price_change_pct:+.2f}%",
        "",
        f"{sig.verdict_emoji} {sig.verdict}",
    ]

    if sig.ls_long is not None and sig.ls_short is not None:
        lines.append(f"⚖️ Л/Ш 1ч: {sig.ls_long:.0f}%/{sig.ls_short:.0f}%")
    else:
        lines.append("⚖️ Л/Ш 1ч: н/д")

    # Ликвидации доступны только с ключом Coinglass — без него строку не показываем
    if sig.liq_short is not None and sig.liq_long is not None:
        lines.append(f"💥 Ликв 1ч: шорты {_fmt_liq(sig.liq_short)} · лонги {_fmt_liq(sig.liq_long)}")

    lines.append(f"📈 OI: 1ч {_fmt_pct(sig.oi_1h)} · 4ч {_fmt_pct(sig.oi_4h)}")
    lines.append(
        f"📊 RSI: 15м {_fmt_rsi(sig.rsi_15m)} · "
        f"1ч {_fmt_rsi(sig.rsi_1h)} · 4ч {_fmt_rsi(sig.rsi_4h)}"
    )

    return "\n".join(lines)


def send_signal(sig: Signal):
    text = format_message(sig)
    try:
        resp = httpx.post(TG_URL, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        resp.raise_for_status()
        log.info(f"Alert sent: {sig.symbol}")
    except Exception as e:
        log.error(f"Failed to send alert for {sig.symbol}: {e}")


def send_signals(signals: list[Signal]):
    now = datetime.utcnow()
    for sig in signals:
        key = (sig.symbol, sig.exchange)
        last = _cooldown.get(key)
        if last and (now - last) < timedelta(minutes=COOLDOWN_MINUTES):
            log.debug(f"Cooldown: {sig.symbol} ({sig.exchange})")
            continue
        send_signal(sig)
        _cooldown[key] = now
        send_trade_signal(sig)   # forward to funding-executor (no-op if URL not set)
