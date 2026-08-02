import sqlite3
import time
from config import DB_PATH


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            funding_rate REAL,
            price REAL,
            oi REAL,
            short_liq REAL,
            next_funding_time INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts_symbol ON snapshots(ts, symbol, exchange)")
    try:
        conn.execute("ALTER TABLE snapshots ADD COLUMN next_funding_time INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def save_snapshots(records: list[dict]) -> int:
    ts = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "INSERT INTO snapshots(ts, symbol, exchange, funding_rate, price, oi, short_liq, next_funding_time) "
        "VALUES (:ts, :symbol, :exchange, :funding_rate, :price, :oi, :short_liq, :next_funding_time)",
        [{**r, "ts": ts, "next_funding_time": r.get("next_funding_time", 0)} for r in records],
    )
    conn.commit()
    conn.close()
    return ts


def get_snapshots_before(ts: int, lookback_seconds: int) -> list[dict]:
    """Ближайший снапшот по каждой паре не новее чем lookback_seconds назад.

    Нижняя граница обязательна. Символы регулярно выпадают из отдельных циклов
    (BingX режет часть ответов на пиковых запросах — разрывов >10м набирается
    под тысячу за 5ч истории), а без floor запрос брал бы любую самую свежую
    подходящую запись, сколь угодно старую. Тогда «цена за 30м» молча считалась бы
    за 2 часа, и после каждого простоя сервиса шли бы сигналы по растянутому окну.
    Лучше отдать пусто и не показать вердикт, чем показать неверный горизонт.
    """
    target = ts - lookback_seconds
    # Допуск = четыре цикла опроса. Записи и в норме приходят с запозданием
    # (цикл ~5м + пропущенные символы), на 30-минутном окне это до 44м.
    floor = target - max(1200, int(lookback_seconds * 0.25))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.*
        FROM snapshots s
        INNER JOIN (
            SELECT symbol, exchange, MAX(ts) AS max_ts
            FROM snapshots
            WHERE ts <= :target
            GROUP BY symbol, exchange
        ) best ON s.symbol = best.symbol AND s.exchange = best.exchange AND s.ts = best.max_ts
        WHERE s.ts >= :floor
    """, {"target": target, "floor": floor}).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def purge_old(older_than_seconds: int = 7200):
    cutoff = int(time.time()) - older_than_seconds
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
    conn.commit()
    conn.close()
