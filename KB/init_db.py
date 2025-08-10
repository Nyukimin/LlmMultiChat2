import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "media.db")
SCHEMA = os.path.join(BASE, "schema.sql")


def init_db() -> None:
    os.makedirs(BASE, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(open(SCHEMA, "r", encoding="utf-8").read())
        conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Initialized: {DB_PATH}")
