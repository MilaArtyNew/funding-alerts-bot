import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Signal thresholds
FUNDING_THRESHOLD = float(os.environ.get("FUNDING_THRESHOLD", "-0.10"))   # funding_now <= X%
FUNDING_DELTA_MIN = float(os.environ.get("FUNDING_DELTA_MIN", "-0.005"))  # min delta to filter float micro-noise
PRICE_CHANGE_MIN = float(os.environ.get("PRICE_CHANGE_MIN", "1.0"))        # %
PRICE_CHANGE_MAX = float(os.environ.get("PRICE_CHANGE_MAX", "10.0"))       # % cap — skip already-pumped coins
# Фильтр по OI: горизонт 1ч, а не 30м (решение 2026-08-15).
#
# Фильтр на 30м снят. Он оставался последним структурным отличием от конкурента:
# на CAP 14.08 16:58 у нас OI 30м был −2.3…−3.8% (в монетах) при его OI 1ч +7.2%
# и 4ч +13.9% — монета росла на часе и падала на получасе, он такие пропускает,
# мы резали. За 22ч лога фильтр 30м отсеял 39 событий по 13 монетам из 62,
# прошедших цену и объём.
#
# OI_1H_MIN — новый порог, «OI 1ч > 0». Считается уже после enrich, потому что
# OI 1ч берётся с Binance (`openInterestHist`, монеты), а не из снапшотов.
# Если OI недоступен (None) — сигнал проходит: конкурент шлёт сигналы по монетам
# с «OI н/д» (OPENEDEN и DOS 14.08, оба закрылись в тейк).
OI_1H_MIN = float(os.environ.get("OI_1H_MIN", "0.0"))                     # % роста OI за 1ч

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

# Вердикт ВХОД: OI растёт на обоих горизонтах + толпа не в лонге.
# Пороги подобраны по 10 сигналам конкурента (совпадение 10/10).
OI_GROWTH_MIN = float(os.environ.get("OI_GROWTH_MIN", "0.1"))      # % роста OI на 1ч и 4ч
SHORT_SHARE_MIN = float(os.environ.get("SHORT_SHARE_MIN", "45"))   # мин. доля шортов, %
CROWD_SHORT_PCT = float(os.environ.get("CROWD_SHORT_PCT", "65"))   # с этой доли помечаем «толпа в шорте»

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "snapshots.db")

# Прогрев: снапшоты копятся, сигналы считаются и пишутся в лог, но никуда не уходят.
# Нужен при переезде — OI 1ч/4ч требуют 4 часа истории, до этого вердикт был бы «н/д».
DRY_RUN = os.environ.get("DRY_RUN", "false").strip().lower() in ("1", "true", "yes", "on")

# Trade executor webhook (funding-executor on VPS) — empty URL disables forwarding
TRADE_WEBHOOK_URL = os.environ.get("TRADE_WEBHOOK_URL", "")
TRADE_WEBHOOK_SECRET = os.environ.get("TRADE_WEBHOOK_SECRET", "")

