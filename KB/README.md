# メディア知識ベース（ローカル）

目的: 「映画/音楽/小説/漫画/アニメ/ボードゲーム/演劇」などの大カテゴリに対して、人（例: 俳優）と作品、出演・役割（クレジット）を正規化して保存し、
- 人→全出演作
- 作品→全出演者（キャスト/スタッフ）
- 連想（FTS検索＋主要関連）
をローカルで高速に照会できるDBを提供します。

採用: SQLite + FTS5（ファイル: `KB/media.db`）。移行容易・ポータブル・依存少。

## ディレクトリ
- `schema.sql` スキーマ定義（カテゴリ/人/作品/役割/クレジット/外部ID/FTS）
  - 統合作品（`unified_work`）とメンバ（`unified_work_member`）により、カテゴリ横断で同一題材を束ねられます
- `init_db.py` DB作成とスキーマ適用
- `example_data.sql` サンプル投入（任意）
- `query_examples.sql` 代表的な問い合わせ集
- `query.py` 簡易CLI（例: 人名→出演作、作品→キャスト）
- `ingest/` CSV取込の雛形

## 使い方
詳細手順は `KB/USAGE.md` を参照してください。
```bash
# 1) DB作成
python KB/init_db.py
# 2) サンプル投入（任意）
sqlite3 KB/media.db ".read KB/example_data.sql"
# 2.5) 統合作品サンプル（任意）
sqlite3 KB/media.db ".read KB/example_unified.sql"
# 3) クエリ例
sqlite3 KB/media.db ".read KB/query_examples.sql"
sqlite3 KB/media.db ".read KB/query_unified.sql"
# 4) CLI
python KB/query.py person "吉沢亮"
python KB/query.py work   "国宝"
```

## 連携
- LLMへの参照は将来 `retriever`（SQLite照会→要約）で接続予定。
- 外部同期（TMDb/Wikipedia等）は `ingest/` にCSVを落とし、`sqlite3 .import` で投入。
