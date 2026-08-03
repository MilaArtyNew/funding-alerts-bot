"""Отправка сигнала торговому исполнителю (funding-executor на VPS).

Никак не влияет на алерты: любая ошибка сети логируется и проглатывается —
сигнальный бот остаётся работоспособным, даже если исполнитель лежит.
"""
import logging

import httpx

from config import TRADE_WEBHOOK_SECRET, TRADE_WEBHOOK_URL
from signal_engine import Signal

log = logging.getLogger(__name__)


def send_trade_signal(sig: Signal):
    if not TRADE_WEBHOOK_URL:
        return

    headers = {"X-Secret": TRADE_WEBHOOK_SECRET} if TRADE_WEBHOOK_SECRET else {}
    payload = {
        "symbol": sig.symbol,
        "price": sig.price_now,
        "strong": sig.strong,
        "verdict": sig.verdict,             # ВХОД | СЛАБЫЙ — исполнитель пишет в статистику
        "verdict_score": sig.verdict_score,
        "funding_now": sig.funding_now,
        "oi_change_pct": sig.oi_change_pct,
        "price_change_pct": sig.price_change_pct,
        "rsi_1h": sig.rsi_1h,
        "ls_short": sig.ls_short,
        # Нужны исполнителю только для статистики: гипотеза «сигналы ближе часа
        # к выплате отрабатывают хуже» проверяется на 30 сделках, а восстановить
        # эти числа задним числом неоткуда — снапшоты живут 5 часов.
        "next_funding_time": sig.next_funding_time,
        "funding_interval_h": sig.funding_interval_h,
    }
    try:
        resp = httpx.post(TRADE_WEBHOOK_URL, json=payload, headers=headers, timeout=8)
        resp.raise_for_status()
        log.info(f"Trade webhook sent: {sig.symbol}")
    except Exception as e:
        log.warning(f"Trade webhook failed for {sig.symbol}: {e}")
