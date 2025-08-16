## 概要

KB はローカル SQLite による知識ベースです。DB は `KB/DB/media.db` に固定し、すべての操作は `KB/api.py` の公式API経由で行います。LLM 側は DB/SQL を直接扱いません。

## 主な構成

- `KB/schema.sql`: スキーマ定義（category/person/work/credit/alias/external_id/fts/unified_*）
- `KB/api.py`: 公式アクセスAPI（初期化/検索/詳細/キャスト/FTS/統合作品）
- `KB/ingest.py`: 取り込み（抽出済みペイロードを正規化・重複抑制の上で登録）
- `KB/normalize.py`: 正規化ルール（タイトル/人物名/役名 など）
- `KB/normalize_db.py`: 既存DBに対する一括正規化/重複整理/FTS再構築
- `KB/DB/media.db`: 実DB
- `KB/DB/backups/`: 初期化(reset)時のバックアップ（最新3件保持）

## DBパス解決ポリシー

- 既定値は `KB/config.yaml` の `db_path`（デフォルト `KB/DB/media.db`）
- 相対パスでサブディレクトリを含む場合は「プロジェクトルート基準」、ファイル名のみは `KB/` 基準
- 公式API `resolve_db_path()` で一元管理

## バックアップ/ローテーション

- `/api/kb/init` または `KB/api.init_db(reset=True)` 実行時、既存DBを `KB/DB/backups/media.db.YYYYMMDD_HHMMSS.bak` にコピー
- バックアップは最新3件のみ保持（古いものは自動削除）

## ログ

- アプリ運用ログは `logs/` に出力（会話・オペレーション・検索の3系統）
- KB初期化時は API 応答 `logs` にも要点を返却

## 依存関係

- 標準: `sqlite3`, `yaml`
- FTS: SQLite FTS5（ビルド済み環境を想定）


