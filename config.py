import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Signal thresholds
FUNDING_THRESHOLD = float(os.environ.get("FUNDING_THRESHOLD", "-0.10"))   # funding_now <= X%
FUNDING_DELTA_MIN = float(os.environ.get("FUNDING_DELTA_MIN", "-0.005"))  # min delta to filter float micro-noise
PRICE_CHANGE_MIN = float(os.environ.get("PRICE_CHANGE_MIN", "1.0"))        # %
PRICE_CHANGE_MAX = float(os.environ.get("PRICE_CHANGE_MAX", "5.0"))        # % cap — skip already-pumped coins
#
# Потолок цены 10% → 5% (2026-08-20). Замер по 43 сделкам, которые удалось
# сопоставить с их сигналами в журнале:
#
#   цена за 30м   сделок    нетто    WR
#   0–2%             30    +6.38$   40%
#   2–3%              4    +0.93$   50%
#   3–5%              1    -0.10$    0%
#   5–10%             8    -8.30$   12%   ← отсекаем
#
# Восемь сделок на уже отлетевших монетах съедали весь плюс остальных 35:
# без них выборка переворачивается с -1.10$ на +7.20$.
#
# Триггер — REDSTONE 20.08 07:58 МСК. В 07:55 он был отсеян на +10.41%, через
# три минуты пролез на +9.87%, не хватило 0.13 п.п. RSI 15м 81 / 1д 74,
# OI 1ч -9.2% — сквиз уже отработал, входить было не во что. Конкурент в тот
# момент был жив (постил HEI в 07:44) и по REDSTONE не выстрелил.

# Фильтр по OI: горизонт 1ч, а не 30м (решение 2026-08-15).
#
# Фильтр на 30м снят. Он оставался последним структурным отличием от конкурента:
# на CAP 14.08 16:58 у нас OI 30м был −2.3…−3.8% (в монетах) при его OI 1ч +7.2%
# и 4ч +13.9% — монета росла на часе и падала на получасе, он такие пропускает,
# мы резали. За 22ч лога фильтр 30м отсеял 39 событий по 13 монетам из 62,
# прошедших цену и объём.
#
# OI_1H_MIN — порог «OI 1ч > 0». Считается уже после enrich, потому что
# OI 1ч берётся с Binance (`openInterestHist`, монеты), а не из снапшотов.
# Если OI недоступен (None) — сигнал проходит: конкурент шлёт сигналы по монетам
# с «OI н/д» (OPENEDEN и DOS 14.08, оба закрылись в тейк).
#
# 2026-08-16: порог выключен (-100). Причина — EPIC 05:02 МСК: у конкурента
# OI 1ч −0.1% и при этом вердикт ВХОД, то есть нуля на OI 1ч у него нет, а это
# было последним структурным отличием после снятия фильтра 30м. За сутки 15-16.08
# порог отсёк NIL и REDSTONE — обе дошли бы до безубытка, суммарно +0.10$,
# то есть ничего не спас. Откат: OI_1H_MIN=0.0 в env.
OI_1H_MIN = float(os.environ.get("OI_1H_MIN", "-100.0"))                  # % роста OI за 1ч, off by default

# Откат к фильтру на 30м: выставить OI_CHANGE_MIN в env (например -1.0).
# По умолчанию выключен — значение заведомо ниже любого реального изменения OI.
OI_CHANGE_MIN = float(os.environ.get("OI_CHANGE_MIN", "-100.0"))          # % OI за 30м, off by default
VOLUME_24H_MIN = float(os.environ.get("VOLUME_24H_MIN", "500000"))         # USD 24h volume — skip illiquid coins
SHORT_LIQ_MIN = float(os.environ.get("SHORT_LIQ_MIN", "200000"))           # USD
COOLDOWN_MINUTES = int(os.environ.get("COOLDOWN_MINUTES", "360"))          # min between same-coin alerts

# Monitoring
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))   # seconds
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "30"))
SNAPSHOT_RETENTION_HOURS = float(os.environ.get("SNAPSHOT_RETENTION_HOURS", "5"))  # нужно ≥4ч для OI 4ч

# Signal context (enrich.py)
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "")   # без него строка ликвидаций не выводится

# Вердикт ВХОД: OI 4ч растёт + толпа не в лонге + рынок не перегрет по дневному RSI.
#
# 2026-08-17: правило переписано по разбору 6 сигналов конкурента за 16-17.08.
# Было «OI 1ч > 0 И OI 4ч > 0 И шорт ≥ 45%» — давало 2/5 совпадений.
# Стало «OI 4ч > 0 И шорт ≥ 45% И RSI 1д < 70» — объясняет 6/6:
#   · HOME с OI 1ч −1.0% у него ВХОД → OI 1ч в вердикте не участвует
#     (второе подтверждение после EPIC 16.08 с OI 1ч −0.1%);
#   · CAP, PORTAL, ONG у него СЛАБЫЙ при RSI 1д 78-80 → дневной RSI гасит вердикт.
#     Именно 1д, а не 4ч: у CAP 4ч всего 62.
# Старая регрессия на 10 сигналах 29-31.07 сохраняется 10/10 — OI 1ч был там
# избыточным условием, ни один вердикт на нём не держался.
#
# Откат: VERDICT_USE_OI_1H=true вернёт условие по OI 1ч, RSI_1D_MAX=1000 снимет RSI.
OI_GROWTH_MIN = float(os.environ.get("OI_GROWTH_MIN", "0.1"))      # % роста OI (4ч, и 1ч если включён)
SHORT_SHARE_MIN = float(os.environ.get("SHORT_SHARE_MIN", "45"))   # мин. доля шортов, %
RSI_1D_MAX = float(os.environ.get("RSI_1D_MAX", "70"))             # выше — вердикт гасится
VERDICT_USE_OI_1H = os.environ.get("VERDICT_USE_OI_1H", "").lower() in ("1", "true", "yes")

# Пометка «на грани»: ширина полосы вокруг OI_GROWTH_MIN, внутри которой значение
# OI 4ч неотличимо от шума измерения.
#
# 2026-08-18: замер на 113 монетах (снапшоты BingX за 5ч против Binance
# `sumOpenInterest` — две законные метрики одной величины) дал медиану
# расхождения по OI 4ч 0.63 п.п., среднее 1.83, максимум 12.9. Порог
# OI_GROWTH_MIN = 0.1 лежит ВНУТРИ этого шума: при нём 40% монет получают
# разный вердикт в зависимости от источника, у половины монет |OI 4ч| вообще
# меньше 0.63 п.п.
#
# Поднять сам порог нельзя — сломает совпадение с конкурентом: у него HOME
# с OI 4ч +0.3% получил ВХОД, значит его порог тоже ~0 (при 1.0 регрессия
# падает 16/16 → 15/16). Поэтому порог оставлен, а сигнал помечается.
#
# 1.5 п.п. ≈ 2.4 медианы шума. На сигнальных монетах бьёт слабее, чем на
# случайных: из 13 сигналов 17-18.08 внутрь полосы попали 5.
# `OI_EDGE_PP=0` выключает пометку.
OI_EDGE_PP = float(os.environ.get("OI_EDGE_PP", "1.5"))
CROWD_SHORT_PCT = float(os.environ.get("CROWD_SHORT_PCT", "65"))   # с этой доли помечаем «толпа в шорте»

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "snapshots.db")

# Прогрев: снапшоты копятся, сигналы считаются и пишутся в лог, но никуда не уходят.
# Нужен при переезде — OI 1ч/4ч требуют 4 часа истории, до этого вердикт был бы «н/д».
DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() in ("1", "true", "yes", "on")

# Trade executor webhook (funding-executor on VPS) — empty URL disables forwarding
TRADE_WEBHOOK_URL = os.environ.get("TRADE_WEBHOOK_URL", "")
TRADE_WEBHOOK_SECRET = os.environ.get("TRADE_WEBHOOK_SECRET", "")

