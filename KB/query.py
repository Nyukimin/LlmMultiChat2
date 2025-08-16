import os
import sqlite3
import sys
from typing import Iterable

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "DB", "media.db")


def rows(cur) -> Iterable[tuple]:
    while True:
        r = cur.fetchone()
        if r is None:
            break
        yield r


def query_person(name: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, name FROM person WHERE name LIKE ? ORDER BY name LIMIT 50",
            (f"%{name}%",),
        )
        people = list(rows(cur))
        if not people:
            print("(no person)")
            return
        for p in people:
            print(f"[Person] {p['id']}: {p['name']}")
            cur2 = conn.execute(
                """
                SELECT w.title, w.year, c.role, c.character
                FROM credit c
                JOIN work w ON w.id=c.work_id
                WHERE c.person_id=?
                ORDER BY w.year NULLS LAST, w.title
                """,
                (p["id"],),
            )
            for r in rows(cur2):
                role = r["role"]
                ch = f" as {r['character']}" if r["character"] else ""
                yr = f" ({r['year']})" if r["year"] else ""
                print(f"  - {r['title']}{yr} [{role}]{ch}")


def query_work(title: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, title, year FROM work WHERE title LIKE ? ORDER BY year DESC, title LIMIT 50",
            (f"%{title}%",),
        )
        works = list(rows(cur))
        if not works:
            print("(no work)")
            return
        for w in works:
            print(f"[Work] {w['id']}: {w['title']} ({w['year'] or '-'})")
            cur2 = conn.execute(
                """
                SELECT p.name, c.role, c.character
                FROM credit c
                JOIN person p ON p.id=c.person_id
                WHERE c.work_id=?
                ORDER BY CASE c.role WHEN 'director' THEN 0 WHEN 'actor' THEN 1 ELSE 9 END, p.name
                """,
                (w["id"],),
            )
            for r in rows(cur2):
                ch = f" as {r['character']}" if r["character"] else ""
                print(f"  - {r['name']} [{r['role']}] {ch}")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python KB/query.py (person|work) <keyword>")
        return
    mode, keyword = sys.argv[1], sys.argv[2]
    if mode == "person":
        query_person(keyword)
    elif mode == "work":
        query_work(keyword)
    else:
        print("mode must be person or work")


if __name__ == "__main__":
    main()
