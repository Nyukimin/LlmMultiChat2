## 概要
- 映画ドメインの検索→抽出→DB登録フローを強化し、DB内容を確認できるビューアUIを追加
- `eiga.com` メイン作品ページ（`https://eiga.com/movie/<id>/`）のみを採用・深掘り
- JSON-LD(Movie)優先でタイトル/年/あらすじ/スタッフ/キャストを抽出
- APIを拡充（詳細取得・サジェスト）し、UIから簡単に利用可能

## 実装内容
- 検索/抽出（`LLM/ingest_mode.py`）
  - 検索順序: `eiga.com → 映画.com/映画com → movies.yahoo.co.jp → .jp`
  - 初回ヒットを拡大・構造化ヒント（人物/作品/年/役割）を付与
  - 深掘り（AllowList: `eiga.com`, `movies.yahoo.co.jp`）で本文精読
  - `eiga.com` はメインURL（`/movie/<id>/`）のみ採用・精読、JSON-LD優先
  - ログ強化: Hints dump / Candidates dump / Credit candidates dump / Deep candidates dump
  - クエリ正規化: 「JSONのみ/前置き禁止」等の混入を自動除去

- API（`LLM/main.py`）
  - 既存: `/api/ingest`, `/api/db/persons`, `/api/db/works`, `/api/db/fts`, `/api/db/unified`
  - 追加:
    - `GET /api/db/persons/{id}`: 人物詳細
    - `GET /api/db/persons/{id}/credits`: 人物のクレジット一覧
    - `GET /api/db/works/{id}`: 作品詳細
    - `GET /api/db/works/{id}/cast`: 作品のキャスト/スタッフ一覧
    - `GET /api/suggest?type=work|person|unknown&q=...`:
      - `type=work` → `site:eiga.com/movie`
      - `type=person` → `site:eiga.com/person`
  - CORS有効化

- UI（`html/kb`）
  - `ingest.html`:
    - トピック種別ラジオ（不明/俳優名/作品名）
    - `eiga.com` サジェストUI（検索→候補→トピック反映）
    - 実行ログにヒント全文・深掘り結果を表示
    - 「DBビューア」リンク追加
  - 追加: `view.html`, `view.js`（DBビューア）
    - 作品/人物/FTS 検索 → リスト → クリックで詳細表示
    - 作品: 詳細＋キャスト/スタッフ
    - 人物: 詳細＋出演作

## 使い方
### 1) セットアップ
```bash
conda activate ChatEnv
pip install -r LLM/requirements.txt
python KB/init_db.py
python -m uvicorn LLM.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2) 収集＆登録（Ingest UI）
- ブラウザで `http://localhost:8000/static/kb/ingest.html`
- 入力例
  - トピック: 国宝
  - 種別: 作品名（必要に応じてサジェストで補助）
  - ドメイン: 映画、巡回: 1〜2、strict: ON
- 期待ログ
  - Hints dump: `https://eiga.com/movie/<id>/` のみ
  - Deep candidates: タイトル/年/あらすじ/監督/脚本/原作/音楽/出演
  - `Registered to DB` が出力されれば登録成功

### 3) DBビューア（表示/検索）
- ブラウザで `http://localhost:8000/static/kb/view.html`
- 作品検索 → 作品クリック → 詳細＋キャスト/スタッフ
- 人物検索 → 人物クリック → 出演作一覧
- FTS検索 → スニペット確認

### 4) API直接確認（例）
- 作品検索: `GET /api/db/works?keyword=国宝`
- 作品詳細: `GET /api/db/works/{id}`
- 作品キャスト: `GET /api/db/works/{id}/cast`
- 人物検索: `GET /api/db/persons?keyword=吉沢`
- 人物詳細: `GET /api/db/persons/{id}`
- 人物クレジット: `GET /api/db/persons/{id}/credits`
- FTS: `GET /api/db/fts?q=国宝*%20OR%20吉沢*`
- サジェスト: `GET /api/suggest?type=work&q=国宝`

## ログ/トラブルシュート
- 実行ログ: `LLM/logs/ingest_conversation.log`
- 操作ログ: `logs/operation_ingest.log`
- 非JSON応答時: `LLM/logs/ingest_raw_r*_<name>.txt` に生ログ保存
- fetchエラー: サーバ起動、CORS、ネットワークを確認

## 変更ファイル（主）
- `LLM/ingest_mode.py`
- `LLM/main.py`
- `html/kb/ingest.html`, `html/kb/ingest.js`, `html/kb/ingest.css`
- `html/kb/view.html`, `html/kb/view.js`

## 注意/今後
- 依存未導入時は `pip install -r LLM/requirements.txt` が必要（fastapi/httpx/uvicorn等）
- 映画以外のドメイン深掘り対応は将来拡張
- 役名抽出の精度向上（パターン拡張）は今後追加可能
