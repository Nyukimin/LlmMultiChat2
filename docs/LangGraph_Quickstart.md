# LangGraph クイックスタート（最新版）

> 注意: コードは LangChain 実装と併存。切替は設定で行います。

## 1) 依存の準備
```bash
cd LLM
pip install -r requirements.txt
```
- 主なレンジ: `langgraph>=0.1.70`, `httpx`, `openai`
- Python 3.9+ 必須

## 2) 設定（提案・承認後）
`LLM/config.yaml` の `conversation.auto_loops` を調整してください（既存維持）

## 3) 起動
```bash
cd LLM
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
- ブラウザ: `http://127.0.0.1:8000/static/`

## 4) 切替/ロールバック
切替は不要（LangChain 依存は排除済み）

## 5) トラブルシュート
- `OPENAI_API_KEY` 未設定: `.env` にセットし再起動
- 生成が止まる: operation/conversation ログでノード名と相関IDを確認
- 指名不全: 応答末尾の `[Next: INTERNAL_ID]` または `{"next":"INTERNAL_ID"}` を確認
