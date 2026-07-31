"""Регрессионный тест вердикта на реальных сигналах конкурента (29–31.07.2026).

Правило восстановлено по этим 10 сигналам, совпадение должно оставаться 10/10.
Запуск: python test_verdict.py
"""
import os

os.environ.setdefault("TELEGRAM_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test")

from enrich import verdict
from signal_engine import Signal


def _sig(ls_short: float, oi_1h: float | None, oi_4h: float | None) -> Signal:
    s = Signal(
        symbol="X-USDT", exchange="BingX", funding_prev=-0.05, funding_now=-0.11,
        funding_delta=-0.06, price_prev=1.0, price_now=1.02, price_change_pct=2.0,
        oi_change_pct=1.0, short_liq=0.0, next_funding_time=0, strong=False,
    )
    s.ls_short, s.ls_long = ls_short, (100 - ls_short if ls_short is not None else None)
    s.oi_1h, s.oi_4h = oi_1h, oi_4h
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

    print(f"\n{'ПРОВАЛ: ' + ', '.join(failed) if failed else 'ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ'}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
