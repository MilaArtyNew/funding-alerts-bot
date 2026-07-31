import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Signal thresholds
FUNDING_THRESHOLD = float(os.environ.get("FUNDING_THRESHOLD", "-0.10"))   # funding_now <= X%
FUNDING_DELTA_MIN = float(os.environ.get("FUNDING_DELTA_MIN", "-0.005"))  # min delta to filter float micro-noise
PRICE_CHANGE_MIN = float(os.environ.get("PRICE_CHANGE_MIN", "1.0"))        # %
PRICE_CHANGE_MAX = float(os.environ.get("PRICE_CHANGE_MAX", "10.0"))       # % cap — skip already-pumped coins
OI_CHANGE_MIN = float(os.environ.get("OI_CHANGE_MIN", "1.0"))             # % OI change required
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

# Trade executor webhook (funding-executor on VPS) — empty URL disables forwarding
TRADE_WEBHOOK_URL = os.environ.get("TRADE_WEBHOOK_URL", "")
TRADE_WEBHOOK_SECRET = os.environ.get("TRADE_WEBHOOK_SECRET", "")

