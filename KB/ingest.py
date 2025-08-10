import os
import sqlite3
from typing import Any, Dict, List, Optional


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    return conn


def _get_or_create_category(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute("SELECT id FROM category WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO category(name) VALUES (?)", (name,))
    return cur.lastrowid


def _get_or_create_person(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute("SELECT id FROM person WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur = conn.execute("INSERT INTO person(name) VALUES (?)", (name,))
    return cur.lastrowid


def _get_or_create_work(
    conn: sqlite3.Connection,
    title: str,
    category: Optional[str] = None,
    year: Optional[int] = None,
    subtype: Optional[str] = None,
    summary: Optional[str] = None,
) -> int:
    cur = conn.execute("SELECT id FROM work WHERE title=?", (title,))
    row = cur.fetchone()
    if row:
        return row[0]
    cat_id = None
    if category:
        cat_id = _get_or_create_category(conn, category)
    else:
        # 未指定時は汎用カテゴリを用意
        cat_id = _get_or_create_category(conn, "その他")
    cur = conn.execute(
        "INSERT INTO work(category_id, title, year, subtype, summary) VALUES (?,?,?,?,?)",
        (cat_id, title, year, subtype, summary),
    )
    return cur.lastrowid


def _create_credit(
    conn: sqlite3.Connection,
    work_id: int,
    person_id: int,
    role: str,
    character: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO credit(work_id, person_id, role, character, note) VALUES (?,?,?,?,?)",
        (work_id, person_id, role, character, note),
    )
    return cur.lastrowid


def _add_alias(conn: sqlite3.Connection, entity_type: str, entity_id: int, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO alias(entity_type, entity_id, name) VALUES (?,?,?)",
        (entity_type, entity_id, name),
    )


def _add_external_id(
    conn: sqlite3.Connection, entity_type: str, entity_id: int, source: str, value: str, url: Optional[str]
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO external_id(entity_type, entity_id, source, value, url) VALUES (?,?,?,?,?)",
        (entity_type, entity_id, source, value, url),
    )


def _unify_work(conn: sqlite3.Connection, name: str, work_id: int, relation: str) -> None:
    cur = conn.execute("SELECT id FROM unified_work WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        uw_id = row[0]
    else:
        cur = conn.execute("INSERT INTO unified_work(name) VALUES (?)", (name,))
        uw_id = cur.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO unified_work_member(unified_work_id, work_id, relation) VALUES (?,?,?)",
        (uw_id, work_id, relation),
    )


def ingest_payload(db_path: str, payload: Dict[str, Any]) -> None:
    """
    payload 例:
    {
      "persons": [{"name":"吉沢亮", "aliases":["Yoshizawa Ryo"]}],
      "works": [{"title":"国宝", "category":"映画", "year":2024}],
      "credits": [{"work":"国宝", "person":"吉沢亮", "role":"actor", "character":null}],
      "unified": [{"name":"国宝", "work":"国宝", "relation":"adaptation"}],
      "external_ids": [{"entity":"work", "name":"国宝", "source":"wikipedia", "value":"国宝_(映画)", "url":"..."}]
    }
    """
    conn = _connect(db_path)
    try:
        with conn:
            # persons
            for p in payload.get("persons", []) or []:
                pid = _get_or_create_person(conn, p.get("name", "").strip())
                for al in (p.get("aliases") or []):
                    _add_alias(conn, "person", pid, al)
            # works
            for w in payload.get("works", []) or []:
                _get_or_create_work(
                    conn,
                    title=w.get("title", "").strip(),
                    category=(w.get("category") or "").strip() or None,
                    year=w.get("year"),
                    subtype=w.get("subtype"),
                    summary=w.get("summary"),
                )
            # credits
            for c in payload.get("credits", []) or []:
                wid = _get_or_create_work(conn, c.get("work", "").strip())
                pid = _get_or_create_person(conn, c.get("person", "").strip())
                _create_credit(conn, wid, pid, c.get("role", "actor"), c.get("character"))
            # external ids
            for ex in payload.get("external_ids", []) or []:
                ent = (ex.get("entity") or "").strip()
                name = (ex.get("name") or "").strip()
                source = (ex.get("source") or "").strip()
                value = (ex.get("value") or "").strip()
                url = ex.get("url")
                if ent == "work":
                    wid = _get_or_create_work(conn, name)
                    _add_external_id(conn, "work", wid, source, value, url)
                elif ent == "person":
                    pid = _get_or_create_person(conn, name)
                    _add_external_id(conn, "person", pid, source, value, url)
            # unified
            for uw in payload.get("unified", []) or []:
                uw_name = uw.get("name") or uw.get("title") or ""
                wid = _get_or_create_work(conn, uw.get("work", "").strip())
                relation = (uw.get("relation") or "related").strip()
                if uw_name:
                    _unify_work(conn, uw_name, wid, relation)
    finally:
        conn.close()


