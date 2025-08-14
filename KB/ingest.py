import os
import sqlite3
from typing import Any, Dict, List, Optional, Callable


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
    prefer_source: Optional[str] = None,
    prefer_value: Optional[str] = None,
) -> int:
    # 1) external_id で一致
    if prefer_source and prefer_value:
        cur = conn.execute(
            "SELECT entity_id FROM external_id WHERE entity_type='work' AND source=? AND value=? LIMIT 1",
            (prefer_source, prefer_value),
        )
        r = cur.fetchone()
        if r:
            return r[0]
    # 2) 正規化タイトルで一致
    norm_title = _normalize_title_for_match(title)
    cur = conn.execute("SELECT id FROM work WHERE title=?", (norm_title,))
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
        (cat_id, norm_title, year, subtype, summary),
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
    # 事前重複チェック
    cur = conn.execute(
        "SELECT id FROM credit WHERE work_id=? AND person_id=? AND role=? AND COALESCE(character,'')=COALESCE(?, '') LIMIT 1",
        (work_id, person_id, role, character),
    )
    row = cur.fetchone()
    if row:
        return row[0]
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
    cur = conn.execute(
        "SELECT id FROM external_id WHERE entity_type=? AND source=? AND value=? LIMIT 1",
        (entity_type, source, value),
    )
    row = cur.fetchone()
    if row:
        return
    conn.execute(
        "INSERT INTO external_id(entity_type, entity_id, source, value, url) VALUES (?,?,?,?,?)",
        (entity_type, entity_id, source, value, url),
    )


def _normalize_title_for_match(title: str) -> str:
    s = (title or "").strip()
    if not s:
        return s
    badges = {"上映中", "配信中", "出演", "声の出演", "声優", "上映予定", "配信予定"}
    parts = [p.strip() for p in s.replace("／", " ").replace("/", " ").split() if p.strip()]
    while parts and parts[0] in badges:
        parts.pop(0)
    return " ".join(parts) or s


def _find_work_by_external(conn: sqlite3.Connection, source: str, value: str) -> Optional[int]:
    cur = conn.execute(
        "SELECT entity_id FROM external_id WHERE entity_type='work' AND source=? AND value=? LIMIT 1",
        (source, value),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _find_person_by_external(conn: sqlite3.Connection, source: str, value: str) -> Optional[int]:
    cur = conn.execute(
        "SELECT entity_id FROM external_id WHERE entity_type='person' AND source=? AND value=? LIMIT 1",
        (source, value),
    )
    row = cur.fetchone()
    return row[0] if row else None


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


def ingest_payload(db_path: str, payload: Dict[str, Any], log_fn: Optional[Callable[[str], None]] = None) -> None:
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
    def _log(msg: str) -> None:
        try:
            if log_fn:
                log_fn(msg)
        except Exception:
            pass
    try:
        with conn:
            # persons
            for p in payload.get("persons", []) or []:
                name = (p.get("name") or "").strip()
                if not name:
                    continue
                # external_id(person) が同梱されていればそれで照合
                pid = None
                for ex in (payload.get("external_ids", []) or []):
                    if (ex.get("entity") or "").strip() == "person" and (ex.get("name") or "").strip() == name:
                        src = (ex.get("source") or "").strip()
                        val = (ex.get("value") or "").strip()
                        if src and val:
                            pid = _find_person_by_external(conn, src, val)
                            if pid is not None:
                                break
                if pid is None:
                    cur = conn.execute("SELECT id,kana,birth_year,death_year,note FROM person WHERE name=?", (name,))
                    row = cur.fetchone()
                    if row:
                        pid = row[0]
                        _log(f"SKIP duplicate person: {name}")
                    else:
                        pid = _get_or_create_person(conn, name)
                        _log(f"ADD person: {name}")
                # Optional fields update (if provided)
                kana = p.get("kana")
                birth_year = p.get("birth_year")
                death_year = p.get("death_year")
                note = p.get("note")
                updates = []
                params = []
                if kana is not None:
                    updates.append("kana=?")
                    params.append(kana)
                if birth_year is not None:
                    updates.append("birth_year=?")
                    params.append(birth_year)
                if death_year is not None:
                    updates.append("death_year=?")
                    params.append(death_year)
                if note is not None:
                    updates.append("note=?")
                    params.append(note)
                if updates:
                    params.append(pid)
                    conn.execute(f"UPDATE person SET {', '.join(updates)} WHERE id=?", tuple(params))
                    _log(f"UPDATE person fields: {name} [{', '.join([u.split('=')[0] for u in updates])}]")
                for al in (p.get("aliases") or []):
                    _add_alias(conn, "person", pid, al)
            # works
            for w in payload.get("works", []) or []:
                title_raw = (w.get("title", "") or "").strip()
                if not title_raw:
                    continue
                norm = _normalize_title_for_match(title_raw)
                cur = conn.execute("SELECT id FROM work WHERE title=?", (norm,))
                row = cur.fetchone()
                existed = bool(row)
                _get_or_create_work(
                    conn,
                    title=title_raw,
                    category=(w.get("category") or "").strip() or None,
                    year=w.get("year"),
                    subtype=w.get("subtype"),
                    summary=w.get("summary"),
                    prefer_source="eiga.com",
                    prefer_value=str((next((ex.get("value") for ex in (payload.get("external_ids") or []) if (ex.get("entity")=="work" and (ex.get("name") or "").strip()==(w.get("title") or "").strip() and (ex.get("source") or "").strip()=="eiga.com")), None) or ""))),
                )
                if existed:
                    _log(f"SKIP duplicate work: {norm}")
                else:
                    _log(f"ADD work: {norm}")
            # credits
            for c in payload.get("credits", []) or []:
                work_title = (c.get("work", "") or "").strip()
                person_name = (c.get("person", "") or "").strip()
                if not work_title or not person_name:
                    continue
                wid = _get_or_create_work(conn, work_title)[0] if isinstance(_get_or_create_work(conn, work_title), tuple) else _get_or_create_work(conn, work_title)
                pid = _get_or_create_person(conn, person_name)[0] if isinstance(_get_or_create_person(conn, person_name), tuple) else _get_or_create_person(conn, person_name)
                cur = conn.execute(
                    "SELECT 1 FROM credit WHERE work_id=? AND person_id=? AND role=? AND COALESCE(character,'')=COALESCE(?, '') LIMIT 1",
                    (wid, pid, c.get("role", "actor"), c.get("character")),
                )
                if cur.fetchone():
                    _log(f"SKIP duplicate credit: {work_title} : {person_name} [{c.get('role','actor')}]")
                else:
                    _create_credit(conn, wid, pid, c.get("role", "actor"), c.get("character"))
                    _log(f"ADD credit: {work_title} : {person_name} [{c.get('role','actor')}]")
            # external ids
            for ex in payload.get("external_ids", []) or []:
                ent = (ex.get("entity") or "").strip()
                name = (ex.get("name") or "").strip()
                source = (ex.get("source") or "").strip()
                value = (ex.get("value") or "").strip()
                url = ex.get("url")
                if ent == "work":
                    wid = _get_or_create_work(conn, name)
                    cur = conn.execute("SELECT 1 FROM external_id WHERE entity_type='work' AND source=? AND value=? LIMIT 1", (source, value))
                    if cur.fetchone():
                        _log(f"SKIP duplicate external_id: work {source}={value}")
                    else:
                        _add_external_id(conn, "work", wid, source, value, url)
                        _log(f"ADD external_id: work {source}={value}")
                elif ent == "person":
                    pid = _get_or_create_person(conn, name)
                    cur = conn.execute("SELECT 1 FROM external_id WHERE entity_type='person' AND source=? AND value=? LIMIT 1", (source, value))
                    if cur.fetchone():
                        _log(f"SKIP duplicate external_id: person {source}={value}")
                    else:
                        _add_external_id(conn, "person", pid, source, value, url)
                        _log(f"ADD external_id: person {source}={value}")
            # unified
            for uw in payload.get("unified", []) or []:
                uw_name = uw.get("name") or uw.get("title") or ""
                wid = _get_or_create_work(conn, uw.get("work", "").strip())
                relation = (uw.get("relation") or "related").strip()
                if uw_name:
                    _unify_work(conn, uw_name, wid, relation)
    finally:
        conn.close()


