## 現状まとめ（Ingest/DB/ビューア）

### 概要
- 検索→抽出→登録の一連を強化し、映画ドメインは `eiga.com` メイン作品ページ（`/movie/<id>/`）のみを採用・深掘り
- LLMのJSON出力を厳格化（前置き禁止・許可キー/ロール限定・マーカー強制）し、修復プロンプト＋深掘りフォールバックで安定登録
- DB確認用ビューア（作品/人物/FTS）を `/static/kb/view.html` として追加

### 実装構成
- 抽出実行: `LLM/ingest_mode.py`
- API: `LLM/main.py`（FastAPI）
- UI: `html/kb/ingest.html`（収集/登録）、`html/kb/view.html`（DBビューア）
- DB: SQLite（`KB/media.db`）、スキーマ `KB/schema.sql`、初期化 `KB/init_db.py`

### 検索フロー（映画）
1) 検索順序: `eiga.com` → 「映画.com/映画com」 → `movies.yahoo.co.jp` → `.jp`
2) 許可ホスト優先、ノイズ（YouTube/TikTok/メルカリ等）除外
3) ヒット件数: クエリ毎に最大12件、全体最大8件を採用
4) `eiga.com` はメイン作品ページ `/movie/<id>/` のみ採用（レビュー/劇場/ニュース等は採用しない）

### 深掘り抽出（AllowList: `eiga.com`, `movies.yahoo.co.jp`）
- `eiga.com` メイン作品ページを最大6件まで取得（Timeout 8s、最大100KB）し、以下を抽出:
  - JSON-LD(Movie)優先: title / year / description / actor / director / author / composer
  - HTMLフォールバック: 監督/脚本/原作/音楽/出演、年、メタdescription
- ログに Deep candidates を出力（タイトル/年/あらすじ/役割別一覧）

### LLMのJSON強制（厳格プロンプト）
- 制約
  - JSONのみ出力、前置き/説明/Markdown（```等）禁止
  - マーカーで囲む: 先頭 `<<<JSON_START>>>`、末尾 `<<<JSON_END>>>`
  - 許可キーのみ: persons, works, credits, external_ids, unified, note, next_queries
  - 許可ロール: actor, voice, director, author, screenplay, composer, theme_song, sound_effects, producer
  - 不明は null / 空配列
- 修復プロンプト
  - JSONだが中身が空の際、スキーマ準拠に修復する指示を別プロンプトで実行
  - なお空なら深掘りペイロードで補完（下）

### フォールバック（Non-JSON/空JSON時）
- `eiga.com/movie/<id>/` を特定し、そのHTMLから自動ペイロードを生成
- 生成内容
  - works: タイトル、年、summary
  - persons: 役割別の人物
  - credits: 作品×人物×役割
  - external_ids: `source=eiga.com`, `value=<id>`, `url` を付与

### UI
- 収集/登録: `/static/kb/ingest.html`
  - トピック種別（不明/俳優名/作品名）
  - `eiga.com` サジェスト（work/person）
  - 実行ログ: Hints/Candidates/Credit candidates/Deep candidates、登録サマリ/詳細
- DBビューア: `/static/kb/view.html`
  - 作品/人物/FTS 検索
  - 作品クリックで詳細＋キャスト/スタッフ
  - 人物クリックで出演作一覧

### API一覧（抜粋）
- POST `/api/ingest` {topic, domain, rounds, strict}
- GET `/api/db/works?keyword=...`
- GET `/api/db/works/{id}`
- GET `/api/db/works/{id}/cast`
- GET `/api/db/persons?keyword=...`
- GET `/api/db/persons/{id}`
- GET `/api/db/persons/{id}/credits`
- GET `/api/db/fts?q=...`
- GET `/api/db/unified?title=...`
- GET `/api/suggest?type=work|person|unknown&q=...`

### 使い方
1) セットアップ
```
conda activate ChatEnv
pip install -r LLM/requirements.txt
python KB/init_db.py
python -m uvicorn LLM.main:app --host 0.0.0.0 --port 8000 --reload
```
2) 収集＆登録
- ブラウザ: `http://localhost:8000/static/kb/ingest.html`
- 例: トピック=「国宝」, 種別=作品名, ドメイン=映画, 巡回=1〜2, strict=ON
- ログに `Registered to DB` と登録サマリが出れば成功
3) 確認
- ビューア: `http://localhost:8000/static/kb/view.html`
- 作品/人物/FTSで確認

### ログ/トラブルシュート
- 実行ログ: `LLM/logs/ingest_conversation.log`
- 操作ログ: `logs/operation_ingest.log`
- 非JSON時の生応答保存: `LLM/logs/ingest_raw_r*_<name>.txt`
- fetchエラー: サーバ起動、CORS、ネットワークを確認

### DB初期化/手動投入
- クリア: `python KB/init_db.py`（`KB/media.db` を再作成）
- 手動投入（例）
```
python -c "import json,sys; sys.path.append('KB'); from ingest import ingest_payload; ingest_payload('KB/media.db', json.loads(open('KB/payload_kokuhou.json','r',encoding='utf-8').read()))"
```

### 既知の制限
- 役名抽出は表記揺れに影響されるため、将来的に正規表現の拡張/ページ個別対応で精度向上予定
- 映画以外ドメインの深掘りは今後拡張予定
