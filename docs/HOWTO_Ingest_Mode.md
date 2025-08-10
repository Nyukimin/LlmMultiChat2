# HOWTO: DB登録専用モード（Ingest Mode）

## 目的
- ユーザーが「映画関連の情報を集めて」等と指示した際、LLM同士の協調で事実をJSONに抽出し、ローカルSQLite DB（`KB/media.db`）へ自動登録します。

## 構成
- `LLM/ingest_mode.py`: 収集ロジック。各キャラに抽出用プロンプトを付与し、JSONを収集・マージ・登録
- `LLM/ingest_main.py`: CLI。トピック/ドメイン/巡回数/DBパスを指定して実行
- `KB/ingest.py`: 受け取ったJSONを`schema.sql`に従って`media.db`へ投入

## JSONスキーマ（検索先行フロー）
```json
{
  "persons": [{ "name": "", "aliases": [""] }],
  "works": [{ "title": "", "category": "映画", "year": 2024, "subtype": null, "summary": null }],
  "credits": [{ "work": "", "person": "", "role": "actor", "character": null }],
  "external_ids": [{ "entity": "work", "name": "", "source": "wikipedia", "value": "", "url": null }],
  "unified": [{ "name": "国宝", "work": "国宝", "relation": "adaptation" }],
  "note": null,
  "next_queries": ["吉沢亮 国宝 映画", "国宝 映画 キャスト"]
}
```

## 使い方（CLI）
```bash
# 収集モードを2巡で実行（映画ドメイン）
python LLM/ingest_main.py "吉沢亮 国宝" --domain 映画 --rounds 2 --db KB/media.db
```
- 標準出力にマージ済みJSONを出力し、DBへ登録します。

## 注意事項
- 収集は「確度の高い事実」重視。推測や未確定は`note`へ、登録は避けてください。
- 既存レコードはキーで同定し、重複登録を避けます（人物=名前、作品=タイトル+カテゴリ、クレジット=作品+人+役割+役名）。
- タイムアウトは各呼び出し60s。
 - 抽出器はDuckDuckGo検索の要約をヒントとして受け取り、厳格なJSONのみを返します（`<<<JSON_START>>> ... <<<JSON_END>>>` マーカー推奨、コードフェンスは避ける）。

## 検証
- DB初期化: `python KB/init_db.py`
- 実行後、代表クエリ: `sqlite3 KB/media.db ".read KB/query_examples.sql"`
- 統合作品の横断: `sqlite3 KB/media.db ".read KB/query_unified.sql"`
