"""Регрессионный тест вердикта на реальных сигналах конкурента (29–31.07.2026).

Правило восстановлено по этим 10 сигналам, совпадение должно оставаться 10/10.
Запуск: python test_verdict.py
"""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test")

from enrich import verdict
from signal_engine import Signal


def _sig(ls_short: float, oi_1h: float | None, oi_4h: float | None,
         rsi_1d: float | None = None) -> Signal:
    s = Signal(
        symbol="X-USDT", exchange="BingX", funding_prev=-0.05, funding_now=-0.11,
        funding_delta=-0.06, price_prev=1.0, price_now=1.02, price_change_pct=2.0,
        oi_change_pct=1.0, short_liq=0.0, next_funding_time=0, strong=False,
    )
    s.ls_short, s.ls_long = ls_short, (100 - ls_short if ls_short is not None else None)
    s.oi_1h, s.oi_4h, s.rsi_1d = oi_1h, oi_4h, rsi_1d
    return s


# coin, ожидаемый вердикт, доля шортов %, OI 1ч %, OI 4ч %
CASES = [
    ("EUL",     "СЛАБЫЙ", 46,  3.5, -1.7),
    ("ESPORTS", "СЛАБЫЙ", 27, -0.0,  0.1),
    ("COTI",    "ВХОД",   52,  0.3,  1.9),
    ("ERA-29",  "СЛАБЫЙ", 62,  0.0, -0.8),
    ("MMT-30",  "ВХОД",   47,  2.5, 12.1),
    ("ESP-30",  "СЛАБЫЙ", 65,  0.3, -7.1),
    ("ERA-31",  "ВХОД",   63,  0.9,  1.7),
    ("RLC",     "СЛАБЫЙ", 39, 10.3,  8.4),
    ("ESP-31",  "СЛАБЫЙ", 62,  0.7, -0.9),
    ("MMT-31",  "ВХОД",   46,  3.1, 12.0),
]


# Сигналы конкурента за 16-17.08.2026 — по ним правило переписано 17.08.
# coin, ожидаемый вердикт, шорт %, OI 1ч %, OI 4ч %, RSI 1д, что решает
NEW_CASES = [
    ("CAP",    "СЛАБЫЙ", 62,  0.0,  0.3, 78, "RSI 1д 78 (4ч всего 62 — решает именно дневной)"),
    ("XAI",    "СЛАБЫЙ", 29,  6.1,  8.1, 58, "шорт 29% < 45%"),
    ("PORTAL", "СЛАБЫЙ", 49,  1.7, 16.8, 78, "RSI 1д 78"),
    ("RVN",    "СЛАБЫЙ", 46,  0.1, -1.4, 36, "OI 4ч −1.4%"),
    ("ONG",    "СЛАБЫЙ", 47, -0.1,  4.3, 78, "RSI 1д 78"),
    ("HOME",   "ВХОД",   56, -1.0,  0.3, 37, "OI 1ч −1.0% не мешает — в правиле его нет"),
]


# Пометка «на грани» (2026-08-18). Ставится, только если переворот условия по
# OI 4ч МЕНЯЕТ вердикт: шум в OI не важен, когда сигнал и так СЛАБЫЙ по RSI/ЛШ.
# coin, шорт %, OI 4ч %, RSI 1д, ожидаемый вердикт, ожидаемая пометка, почему
EDGE_CASES = [
    ("HOME 17.08", 56,   0.3, 37, "ВХОД",   True,
     "реальный сигнал: единственный ВХОД держится на OI 4ч +0.3%"),
    ("CAP 17.08",  62,   0.3, 78, "СЛАБЫЙ", False,
     "OI в полосе, но СЛАБЫЙ решает RSI 78 — шум в OI ничего не меняет"),
    ("XAI 16.08",  29,   8.1, 58, "СЛАБЫЙ", False,
     "OI решителен (8.1), да и шорт 29% всё равно валит"),
    ("на грани −", 60,  -1.0, 40, "СЛАБЫЙ", True,
     "минус внутри полосы: у другого источника был бы ВХОД"),
    ("уверенный +", 60,  8.0, 40, "ВХОД",   False,
     "OI 8.0 далеко за полосой"),
    ("уверенный −", 60, -5.0, 40, "СЛАБЫЙ", False,
     "OI −5.0 далеко за полосой"),
    ("край полосы", 60,  1.6, 40, "ВХОД",   False,
     "|1.6 − 0.1| = 1.5 — ровно на границе, полоса строго меньше"),
]


def main():
    failed = []
    for coin, expected, ls_short, oi_1h, oi_4h in CASES:
        _, got, score = verdict(_sig(ls_short, oi_1h, oi_4h))
        mark = "ok" if got == expected else "МИМО"
        if got != expected:
            failed.append(coin)
        print(f"{coin:9} ожидали {expected:7} получили {got:7} (баллов {score:.0f}/3)  {mark}")

    # Без OI правило не считается вообще
    sig = _sig(60, 1.0, None)
    _, got, _ = verdict(sig)
    print(f"{'нет OI 4ч':12} → {got} (ожидали н/д)")
    if got != "н/д":
        failed.append("нет OI 4ч")

    # Без Л/Ш решаем по двум условиям и помечаем неполноту
    for name, ls, oi1, oi4, expected in (
        ("нет Л/Ш, OI+", None, 1.0, 1.0, "ВХОД"),
        ("нет Л/Ш, OI-", None, 1.0, -1.0, "СЛАБЫЙ"),
    ):
        sig = _sig(ls, oi1, oi4)
        _, got, _ = verdict(sig)
        ok = got == expected and sig.verdict_partial
        print(f"{name:12} → {got}, пометка «без Л/Ш»: {sig.verdict_partial} (ожидали {expected})")
        if not ok:
            failed.append(name)

    # --- Порция 16-17.08: по ней правило и переписано. Должно совпасть 6/6.
    #     Здесь дневной RSI известен, поэтому работают все три условия.
    print()
    for coin, expected, ls_short, oi_1h, oi_4h, rsi_1d, why in NEW_CASES:
        _, got, score = verdict(_sig(ls_short, oi_1h, oi_4h, rsi_1d))
        mark = "ok" if got == expected else "МИМО"
        if got != expected:
            failed.append(coin)
        print(f"{coin:9} ожидали {expected:7} получили {got:7} (баллов {score:.0f}/3)  "
              f"{mark:5} {why}")

    # --- Пометка «на грани»: сам вердикт не меняет, только помечает неустойчивость
    print()
    for coin, ls_short, oi_4h, rsi_1d, exp_v, exp_edge, why in EDGE_CASES:
        sig = _sig(ls_short, 1.0, oi_4h, rsi_1d)
        _, got, _ = verdict(sig)
        ok = got == exp_v and sig.verdict_edge == exp_edge
        if not ok:
            failed.append(coin)
        print(f"{coin:12} {got:7} на грани={str(sig.verdict_edge):5} "
              f"(ждали {exp_v}/{exp_edge})  {'ok' if ok else 'МИМО':5} {why}")

    print(f"\n{'ПРОВАЛ: ' + ', '.join(failed) if failed else 'ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ'}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
