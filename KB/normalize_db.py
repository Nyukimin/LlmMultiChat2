from __future__ import annotations
import argparse
import datetime as dt
import os
import sys
import sqlite3
from typing import Dict, Any

# Ensure project root is importable when running this file directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
if _ROOT_DIR not in sys.path:
	sys.path.insert(0, _ROOT_DIR)

# Reuse the shared normalization
from KB.normalize import normalize_title, normalize_person_name, normalize_credit, normalize_role, normalize_character, is_noise_person_name


def backup_db(db_path: str) -> str:
	os.makedirs(os.path.join(os.path.dirname(db_path), "backup"), exist_ok=True)
	stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
	bk = os.path.join(os.path.dirname(db_path), "backup", f"media_{stamp}.db")
	import shutil
	shutil.copy2(db_path, bk)
	return bk


def normalize_all(db_path: str, apply: bool) -> Dict[str, Any]:
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	stats: Dict[str, Any] = {"works": 0, "persons": 0, "aliases": 0, "credits": 0, "works_changed": 0, "persons_changed": 0, "aliases_changed": 0, "credits_changed": 0}
	with conn:
		# works
		cur = conn.execute("SELECT id, title, year FROM work")
		rows = cur.fetchall()
		for r in rows:
			new_title, new_year = normalize_title(r["title"] or "")
			changed = (new_title != (r["title"] or "")) or (new_year != (r["year"] if r["year"] is not None else None))
			stats["works"] += 1
			if changed:
				stats["works_changed"] += 1
				if apply:
					conn.execute("UPDATE work SET title=?, year=? WHERE id=?", (new_title, new_year, r["id"]))

		# persons
		cur = conn.execute("SELECT id, name FROM person")
		rows = cur.fetchall()
		for r in rows:
			raw = r["name"] or ""
			new_name = normalize_person_name(raw)
			stats["persons"] += 1
			if is_noise_person_name(raw):
				# ノイズ人物は削除（関連も連鎖削除）
				if apply:
					conn.execute("DELETE FROM alias WHERE entity_type='person' AND entity_id=?", (r["id"],))
					conn.execute("DELETE FROM external_id WHERE entity_type='person' AND entity_id=?", (r["id"],))
					conn.execute("DELETE FROM person WHERE id=?", (r["id"],))
				stats["persons_changed"] += 1
			else:
				changed = new_name != raw
				if changed:
					stats["persons_changed"] += 1
					if apply:
						conn.execute("UPDATE person SET name=? WHERE id=?", (new_name, r["id"]))

		# aliases
		cur = conn.execute("SELECT id, name FROM alias")
		rows = cur.fetchall()
		for r in rows:
			new_name = normalize_person_name(r["name"] or "")
			changed = new_name != (r["name"] or "")
			stats["aliases"] += 1
			if changed:
				stats["aliases_changed"] += 1
				if apply:
					conn.execute("UPDATE alias SET name=? WHERE id=?", (new_name, r["id"]))

		# credits (schema: id, work_id, person_id, role, character, note)
		cur = conn.execute("SELECT id, role, character FROM credit")
		rows = cur.fetchall()
		for r in rows:
			new_role = normalize_role(r["role"] or "")
			new_char = normalize_character(r["character"] or "")
			changed = (new_role != (r["role"] or "")) or (new_char != (r["character"] or ""))
			stats["credits"] += 1
			if changed:
				stats["credits_changed"] += 1
				if apply:
					conn.execute("UPDATE credit SET role=?, character=? WHERE id=?", (new_role, new_char, r["id"]))

		# Rebuild FTS if exists
		try:
			conn.execute("INSERT INTO fts(fts) VALUES('delete-all')")
			conn.execute("INSERT INTO fts(rowid, content) SELECT id, title FROM work")
		except Exception:
			pass

	return stats


def main():
	p = argparse.ArgumentParser(description="Normalize entire KB using LLM/normalize.py")
	p.add_argument("--db", required=True)
	p.add_argument("--apply", action="store_true")
	p.add_argument("--dry-run", action="store_true")
	args = p.parse_args()

	if args.apply and args.dry_run:
		print("Specify either --apply or --dry-run")
		return
	if not args.apply and not args.dry_run:
		print("Specify --dry-run or --apply")
		return

	bk = None
	if args.apply:
		bk = backup_db(args.db)
		print(f"Backup: {bk}")

	stats = normalize_all(args.db, apply=args.apply)
	print(stats)


if __name__ == "__main__":
	main()
