import os
import sqlite3
from typing import Any, Callable, Dict, List, Optional

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_db_path() -> str:
    """Resolve DB path from KB/config.yaml (relative allowed). Defaults to KB/DB/media.db."""
    cfg_path = os.path.join(BASE_DIR, 'config.yaml')
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        db_path = cfg.get('db_path') or 'DB/media.db'
        if not os.path.isabs(db_path):
            # relative to project root if subdir included, else KB dir
            if ('/' in db_path) or ('\\' in db_path):
                root = os.path.abspath(os.path.join(BASE_DIR, '..'))
                return os.path.abspath(os.path.join(root, db_path))
            return os.path.abspath(os.path.join(BASE_DIR, db_path))
        return db_path
    except Exception:
        return os.path.abspath(os.path.join(BASE_DIR, 'DB', 'media.db'))


def _open(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or resolve_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(reset: bool = False, db_path: Optional[str] = None) -> Dict[str, Any]:
    path = db_path or resolve_db_path()
    schema_path = os.path.join(BASE_DIR, 'schema.sql')
    logs: List[str] = []
    existed = os.path.exists(path)
    did_reset = False
    # rotate backups when reset
    if reset and existed:
        try:
            backups_dir = os.path.join(BASE_DIR, 'DB', 'backups')
            os.makedirs(backups_dir, exist_ok=True)
            import datetime, shutil
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            base = os.path.basename(path)
            bak_path = os.path.join(backups_dir, f"{base}.{ts}.bak")
            shutil.copy2(path, bak_path)
            logs.append(f"backup saved: {bak_path}")
            # prune to 3
            files = sorted([
                os.path.join(backups_dir, f) for f in os.listdir(backups_dir)
                if f.startswith(base + '.')
            ], key=lambda p: os.path.getmtime(p), reverse=True)
            for old in files[3:]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception as e:
            logs.append(f"backup failed: {e}")
        try:
            os.remove(path)
            did_reset = True
            logs.append(f"removed existing DB: {path}")
        except Exception as e:
            logs.append(f"failed to remove DB: {e}")
    # apply schema
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
    with sqlite3.connect(path) as conn:
        conn.executescript(schema_sql)
        conn.commit()
        # stats
        stats: Dict[str, Any] = {}
        for t in ["person", "work", "credit", "external_id", "alias", "unified_work", "unified_work_member"]:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {t}")
                stats[t] = int(cur.fetchone()[0])
            except Exception:
                stats[t] = None
    logs.append("schema applied")
    return {
        "ok": True,
        "db_path": path,
        "existed_before": existed,
        "did_reset": did_reset,
        "stats": stats,
        "logs": logs,
    }


def persons_search(keyword: str, db_path: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with _open(db_path) as conn:
        cur = conn.execute(
            "SELECT id, name FROM person WHERE name LIKE ? ORDER BY name LIMIT ?",
            (f"%{keyword}%", limit),
        )
        return [dict(r) for r in cur.fetchall()]


def person_detail(person_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _open(db_path) as conn:
        cur = conn.execute("SELECT id, name, kana, birth_year, death_year, note FROM person WHERE id=?", (person_id,))
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        cur2 = conn.execute("SELECT source, value, url FROM external_id WHERE entity_type='person' AND entity_id=? ORDER BY source", (person_id,))
        item["external_ids"] = [dict(r) for r in cur2.fetchall()]
        return item


def person_credits(person_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _open(db_path) as conn:
        cur = conn.execute(
            """
            SELECT w.id AS work_id, w.title, w.year, c.role, c.character
            FROM credit c
            JOIN work w ON w.id=c.work_id
            WHERE c.person_id=?
            ORDER BY w.year IS NULL, w.year, w.title
            """,
            (person_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def works_search(keyword: str, db_path: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with _open(db_path) as conn:
        cur = conn.execute(
            "SELECT id, title, year FROM work WHERE title LIKE ? ORDER BY year DESC, title LIMIT ?",
            (f"%{keyword}%", limit),
        )
        return [dict(r) for r in cur.fetchall()]


def work_detail(work_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _open(db_path) as conn:
        cur = conn.execute(
            """
            SELECT w.id, w.title, w.year, w.subtype, w.summary, c.name AS category
            FROM work w
            JOIN category c ON c.id = w.category_id
            WHERE w.id=?
            """,
            (work_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        item = dict(row)
        cur2 = conn.execute("SELECT source, value, url FROM external_id WHERE entity_type='work' AND entity_id=? ORDER BY source", (work_id,))
        item["external_ids"] = [dict(r) for r in cur2.fetchall()]
        return item


def work_cast(work_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _open(db_path) as conn:
        cur = conn.execute(
            """
            SELECT p.id AS person_id, p.name, c.role, c.character
            FROM credit c
            JOIN person p ON p.id=c.person_id
            WHERE c.work_id=?
            ORDER BY CASE c.role WHEN 'director' THEN 0 WHEN 'actor' THEN 1 ELSE 9 END, p.name
            """,
            (work_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def fts_search(q: str, db_path: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with _open(db_path) as conn:
        cur = conn.execute(
            "SELECT kind, ref_id, snippet(fts, 1, '[', ']', '...', 10) AS snippet FROM fts WHERE fts MATCH ? LIMIT ?",
            (q, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def unified_by_title(title_like: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with _open(db_path) as conn:
        sql = (
            """
            WITH target AS (
              SELECT uw.id AS unified_id
              FROM work w
              JOIN unified_work_member uwm ON uwm.work_id=w.id
              JOIN unified_work uw ON uw.id=uwm.unified_work_id
              WHERE w.title LIKE ?
              LIMIT 1
            )
            SELECT w.id AS work_id, w.title, w.year, c.name AS category, uwm.relation
            FROM unified_work_member uwm
            JOIN work w ON w.id=uwm.work_id
            JOIN category c ON c.id=w.category_id
            JOIN target t ON t.unified_id=uwm.unified_work_id
            ORDER BY w.year, w.title
            """
        )
        cur = conn.execute(sql, (f"%{title_like}%",))
        return [dict(r) for r in cur.fetchall()]


