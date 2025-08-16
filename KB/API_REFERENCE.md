# KB API リファレンス

このドキュメントは、KB の利用に必要な API をすべて列挙します。KB 内のドキュメント（本ファイル、`KB/DESIGN.md`, `KB/USAGE.md`）だけで、初期化・登録・参照・保守が完結します。

- DB 位置: `KB/DB/media.db`
- バックアップ: `KB/DB/backups/`（初期化時に最新3件保持）
- 公式API: `KB/api.py`
- サーバ経由HTTP API: `LLM/main.py` が `KB/api.py` をプロキシ

---

## 1. Python API（`from KB import api as kb`）

- 共通
  - `kb.resolve_db_path() -> str`
    - `KB/config.yaml` の `db_path` を解決（相対可）。既定 `KB/DB/media.db`。

- 初期化
  - `kb.init_db(reset: bool=False, db_path: str|None=None) -> dict`
    - 入力: `reset=True` で既存DBをバックアップしてから再作成
    - 返却例:
```python
{
  "ok": True,
  "db_path": "E:/.../KB/DB/media.db",
  "existed_before": True,
  "did_reset": True,
  "stats": {"person": 0, "work": 0, ...},
  "logs": ["backup saved: ...", "schema applied"]
}
```

- 検索/詳細（人物）
  - `kb.persons_search(keyword: str, db_path: str|None=None, limit: int=50) -> list[dict]`
  - `kb.person_detail(person_id: int, db_path: str|None=None) -> dict|None`
    - `item.external_ids: [{source, value, url|null}]` を同梱
  - `kb.person_credits(person_id: int, db_path: str|None=None) -> list[dict]`

- 検索/詳細（作品）
  - `kb.works_search(keyword: str, db_path: str|None=None, limit: int=50) -> list[dict]`
  - `kb.work_detail(work_id: int, db_path: str|None=None) -> dict|None`
    - `item.external_ids: [{source, value, url|null}]` を同梱
  - `kb.work_cast(work_id: int, db_path: str|None=None) -> list[dict]`

- 横断
  - `kb.fts_search(q: str, db_path: str|None=None, limit: int=50) -> list[dict]`
  - `kb.unified_by_title(title_like: str, db_path: str|None=None) -> list[dict]`

- 例:
```python
from KB import api as kb
kb.init_db(reset=True)
people = kb.persons_search("吉沢")
if people:
    pid = people[0]["id"]
    print(kb.person_detail(pid))
    print(kb.person_credits(pid)[:3])
works = kb.works_search("キングダム")
if works:
    wid = works[0]["id"]
    print(kb.work_detail(wid))
    print(kb.work_cast(wid)[:5])
```

---

## 2. HTTP API（サーバ経由）

- 初期化
  - `POST /api/kb/init`
    - Body: `{ "reset": true|false }`
    - 返却: Python API `init_db` と同じ構造

- DBパス確認
  - `GET /api/db/path`
    - 返却: `{ ok: true, db: ".../KB/DB/media.db" }`

- 人物
  - `GET /api/db/persons?keyword=...`
    - 返却: `{ ok: true, items: [{id, name}] }`
  - `GET /api/db/persons/{person_id}`
    - 返却: `{ ok: true, item: { id, name, kana, birth_year, death_year, note, external_ids: [...] } }`
  - `GET /api/db/persons/{person_id}/credits`
    - 返却: `{ ok: true, items: [{ work_id, title, year, role, character }] }`

- 作品
  - `GET /api/db/works?keyword=...`
    - 返却: `{ ok: true, items: [{id, title, year}] }`
  - `GET /api/db/works/{work_id}`
    - 返却: `{ ok: true, item: { id, title, year, subtype, summary, category, external_ids: [...] } }`
  - `GET /api/db/works/{work_id}/cast`
    - 返却: `{ ok: true, items: [{ person_id, name, role, character }] }`

- 横断
  - `GET /api/db/fts?q=...&limit=50`
    - 返却: `{ ok: true, items: [{ kind, ref_id, snippet }] }`
  - `GET /api/db/unified?title=...`
    - 返却: `{ ok: true, items: [{ work_id, title, year, category, relation }] }`

- 例（PowerShell）:
```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/db/persons?keyword=吉沢" | ConvertTo-Json -Depth 6
Invoke-RestMethod "http://127.0.0.1:8000/api/db/works?keyword=キングダム" | ConvertTo-Json -Depth 6
```

- エラー形式
  - 200 + `{ ok: false, error: "..." }`（サーバ側で例外捕捉時）

---

## 3. スキーマ要点（`KB/schema.sql`）
- `person`, `work`, `credit`, `alias`, `external_id`, `fts`, `unified_work`, `unified_work_member`
- FTS5 を使用。`person/work/credit` への INSERT/UPDATE/DELETE に同期トリガを設定
- 一意制約: `alias(entity_type, entity_id, name)`, `external_id(entity_type, entity_id, source)`

---

## 4. バックアップ/ローテーション
- `init_db(reset=True)` 実行時に `KB/DB/backups/media.db.YYYYMMDD_HHMMSS.bak` を作成
- 最新3件のみ保持、古いものは自動削除

---

## 5. ログ運用
- 初期化時は `logs`（応答のlogs配列）に要点記録
- アプリ運用ログは `logs/` 直下（会話/オペレーション/検索）

---

## 6. ベストプラクティス
- LLM/アプリ層は必ず `KB/api.py` のAPIを利用し、DBパスやSQL本文に依存しない
- DBパスは `KB/config.yaml` で一元管理
- 外部ID（eiga.com 等）は登録時に重複抑止（UNIQUE）
- 正規化は `KB/normalize.py` を使用し、入力データを必ずクレンジング
