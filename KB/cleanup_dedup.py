import os
import re
import shutil
import sqlite3
from datetime import datetime
from typing import Dict, List, Tuple, Optional


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _normalize_title_for_match(title: str) -> str:
    s = (title or "").strip()
    if not s:
        return s
    badges = {"上映中", "配信中", "出演", "声の出演", "声優", "上映予定", "配信予定"}
    parts = [p.strip() for p in s.replace("／", " ").replace("/", " ").split() if p.strip()]
    while parts and parts[0] in badges:
        parts.pop(0)
    return " ".join(parts) or s


def _backup_db(src_db_path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    base_dir = os.path.dirname(os.path.abspath(src_db_path))
    base_name = os.path.splitext(os.path.basename(src_db_path))[0]
    dst = os.path.join(base_dir, f"{base_name}_{ts}.db")
    shutil.copy2(src_db_path, dst)
    return dst


def _dedup_persons(conn: sqlite3.Connection, dry_run: bool, logs: List[str]) -> Dict[str, int]:
    stats = {"merged": 0, "removed": 0, "groups": 0}
    # 名前（空白正規化）でグルーピング
    cur = conn.execute("SELECT id, name FROM person")
    rows = cur.fetchall()
    groups: Dict[str, List[int]] = {}
    for r in rows:
        canon = _normalize_spaces(r["name"])
        groups.setdefault(canon, []).append(int(r["id"]))
    for canon, ids in groups.items():
        if len(ids) <= 1:
            continue
        ids_sorted = sorted(ids)
        primary = ids_sorted[0]
        dupes = ids_sorted[1:]
        stats["groups"] += 1
        logs.append(f"person merge group: '{canon}' -> keep {primary}, remove {dupes}")
        if not dry_run:
            # 参照付替え
            conn.execute("UPDATE OR IGNORE credit SET person_id=? WHERE person_id IN (%s)" % ",".join(["?"]*len(dupes)), (primary, *dupes))
            conn.execute("UPDATE OR IGNORE alias SET entity_id=? WHERE entity_type='person' AND entity_id IN (%s)" % ",".join(["?"]*len(dupes)), (primary, *dupes))
            # external_id は UNIQUE(entity_type, entity_id, source) 制約のため、競合は先に重複を削除
            for pid in dupes:
                # 競合する source を削除（同一sourceが既にprimaryにある場合）
                conn.execute(
                    "DELETE FROM external_id WHERE entity_type='person' AND entity_id=? AND source IN (SELECT source FROM external_id WHERE entity_type='person' AND entity_id=?)",
                    (pid, primary),
                )
                conn.execute("UPDATE external_id SET entity_id=? WHERE entity_type='person' AND entity_id=?", (primary, pid))
                conn.execute("DELETE FROM person WHERE id=?", (pid,))
            stats["merged"] += len(dupes)
            stats["removed"] += len(dupes)
    return stats


def _dedup_works(conn: sqlite3.Connection, dry_run: bool, logs: List[str]) -> Dict[str, int]:
    stats = {"merged": 0, "removed": 0, "groups": 0}
    # 正規化タイトル + カテゴリ + 年 でグルーピング
    cur = conn.execute(
        """
        SELECT w.id, w.title, w.year, w.category_id FROM work w
        """
    )
    rows = cur.fetchall()
    groups: Dict[Tuple[str, Optional[int], Optional[int]], List[int]] = {}
    for r in rows:
        norm = _normalize_title_for_match(r["title"]) or r["title"]
        k = (norm, int(r["category_id"]) if r["category_id"] is not None else None, int(r["year"]) if r["year"] is not None else None)
        groups.setdefault(k, []).append(int(r["id"]))
    for key, ids in groups.items():
        if len(ids) <= 1:
            continue
        ids_sorted = sorted(ids)
        primary = ids_sorted[0]
        dupes = ids_sorted[1:]
        stats["groups"] += 1
        logs.append(f"work merge group: {key} -> keep {primary}, remove {dupes}")
        if not dry_run:
            conn.execute("UPDATE OR IGNORE credit SET work_id=? WHERE work_id IN (%s)" % ",".join(["?"]*len(dupes)), (primary, *dupes))
            conn.execute("UPDATE OR IGNORE alias SET entity_id=? WHERE entity_type='work' AND entity_id IN (%s)" % ",".join(["?"]*len(dupes)), (primary, *dupes))
            # external_id (UNIQUE(entity_type, entity_id, source)) の競合対処
            for wid in dupes:
                conn.execute(
                    "DELETE FROM external_id WHERE entity_type='work' AND entity_id=? AND source IN (SELECT source FROM external_id WHERE entity_type='work' AND entity_id=?)",
                    (wid, primary),
                )
                conn.execute("UPDATE external_id SET entity_id=? WHERE entity_type='work' AND entity_id=?", (primary, wid))
                # 統合作品メンバ付替え
                conn.execute("UPDATE OR IGNORE unified_work_member SET work_id=? WHERE work_id=?", (primary, wid))
                conn.execute("DELETE FROM work WHERE id=?", (wid,))
            stats["merged"] += len(dupes)
            stats["removed"] += len(dupes)
    return stats


def _dedup_credits(conn: sqlite3.Connection, dry_run: bool, logs: List[str]) -> Dict[str, int]:
    stats = {"removed": 0}
    cur = conn.execute(
        """
        SELECT work_id, person_id, role, COALESCE(character,'') AS ch, GROUP_CONCAT(id) AS ids, COUNT(*) AS cnt
        FROM credit
        GROUP BY work_id, person_id, role, COALESCE(character,'')
        HAVING COUNT(*) > 1
        """
    )
    for r in cur.fetchall():
        ids = [int(x) for x in str(r["ids"]).split(",") if x]
        ids_sorted = sorted(ids)
        keep = ids_sorted[0]
        remove = ids_sorted[1:]
        logs.append(f"credit duplicates: keep {keep}, remove {remove} for (work={r['work_id']}, person={r['person_id']}, role={r['role']}, ch='{r['ch']}')")
        if not dry_run and remove:
            conn.execute("DELETE FROM credit WHERE id IN (%s)" % ",".join(["?"]*len(remove)), remove)
            stats["removed"] += len(remove)
    return stats


def _dedup_external_ids(conn: sqlite3.Connection, dry_run: bool, logs: List[str]) -> Dict[str, int]:
    stats = {"removed": 0}
    cur = conn.execute(
        """
        SELECT entity_type, entity_id, source, value, GROUP_CONCAT(id) AS ids, COUNT(*) AS cnt
        FROM external_id
        GROUP BY entity_type, entity_id, source, value
        HAVING COUNT(*) > 1
        """
    )
    for r in cur.fetchall():
        ids = [int(x) for x in str(r["ids"]).split(",") if x]
        ids_sorted = sorted(ids)
        keep = ids_sorted[0]
        remove = ids_sorted[1:]
        logs.append(f"external_id duplicates: keep {keep}, remove {remove} for ({r['entity_type']},{r['entity_id']},{r['source']}={r['value']})")
        if not dry_run and remove:
            conn.execute("DELETE FROM external_id WHERE id IN (%s)" % ",".join(["?"]*len(remove)), remove)
            stats["removed"] += len(remove)
    return stats


def _rebuild_fts(conn: sqlite3.Connection, dry_run: bool, logs: List[str]) -> Dict[str, int]:
    stats = {"inserted": 0}
    if dry_run:
        # 推定件数のみ
        pc = conn.execute("SELECT COUNT(*) FROM person").fetchone()[0]
        wc = conn.execute("SELECT COUNT(*) FROM work").fetchone()[0]
        cc = conn.execute("SELECT COUNT(*) FROM credit").fetchone()[0]
        stats["inserted"] = pc + wc + cc
        logs.append(f"FTS rebuild (dry-run): approx rows={stats['inserted']}")
        return stats
    # FTS5 contentless の全削除は特殊コマンドで実施
    try:
        conn.execute("INSERT INTO fts(fts) VALUES('delete-all')")
    except Exception as e:
        logs.append(f"FTS delete-all failed (ignored): {e}")
    # person
    for r in conn.execute("SELECT id, COALESCE(name,'') AS name, COALESCE(kana,'') AS kana FROM person"):
        conn.execute("INSERT INTO fts(kind, ref_id, text) VALUES ('person', ?, ?)", (r["id"], f"{r['name']} {r['kana']}") )
        stats["inserted"] += 1
    # work
    for r in conn.execute("SELECT id, COALESCE(title,'') AS title, COALESCE(summary,'') AS summary FROM work"):
        conn.execute("INSERT INTO fts(kind, ref_id, text) VALUES ('work', ?, ?)", (r["id"], f"{r['title']} {r['summary']}") )
        stats["inserted"] += 1
    # credit
    for r in conn.execute("SELECT id, COALESCE(character,'') AS ch, COALESCE(role,'') AS role FROM credit"):
        conn.execute("INSERT INTO fts(kind, ref_id, text) VALUES ('credit', ?, ?)", (r["id"], f"{r['ch']} {r['role']}") )
        stats["inserted"] += 1
    logs.append(f"FTS rebuilt rows={stats['inserted']}")
    return stats


def run_cleanup(db_path: str, dry_run: bool = True, vacuum: bool = False) -> Dict[str, object]:
    """一括クリーンアップ（重複排除/統合/FTS再構築/VACUUM）。
    戻り値には統計とログ、バックアップファイル（実行時のみ）を含める。
    """
    path = os.path.abspath(db_path)
    logs: List[str] = []
    result: Dict[str, object] = {"ok": True, "backup_path": None, "stats": {}, "logs": logs}
    if not os.path.exists(path):
        return {"ok": False, "error": f"DB not found: {path}", "logs": []}
    backup_path = None
    if not dry_run:
        backup_path = _backup_db(path)
        result["backup_path"] = backup_path
        logs.append(f"Backup created: {backup_path}")
    try:
        with _connect(path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            # トランザクション（VACUUMは後段で実施）
            with conn:
                s_person = _dedup_persons(conn, dry_run, logs)
                s_work = _dedup_works(conn, dry_run, logs)
                s_credit = _dedup_credits(conn, dry_run, logs)
                s_ext = _dedup_external_ids(conn, dry_run, logs)
                s_fts = _rebuild_fts(conn, dry_run, logs)
            result["stats"] = {
                "person": s_person,
                "work": s_work,
                "credit": s_credit,
                "external_id": s_ext,
                "fts": s_fts,
            }
        # VACUUM はトランザクション外で別フェーズとして実施
        if not dry_run and vacuum:
            with sqlite3.connect(path) as vconn:
                vconn.execute("VACUUM")
            logs.append("VACUUM executed")
    except Exception as e:
        result = {"ok": False, "error": str(e), "backup_path": backup_path, "logs": logs}
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("db", help="Path to SQLite DB")
    p.add_argument("--exec", action="store_true", help="Execute (not dry-run)")
    p.add_argument("--vacuum", action="store_true", help="Run VACUUM after cleanup")
    args = p.parse_args()
    res = run_cleanup(args.db, dry_run=(not args.exec), vacuum=args.vacuum)
    import json
    print(json.dumps(res, ensure_ascii=False, indent=2))


