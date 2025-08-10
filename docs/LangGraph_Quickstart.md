# LangGraph クイックスタート（最新版）

> 注意: コードは LangChain 実装と併存。切替は設定で行います。

## 1) 依存の準備
```bash
cd LLM
pip install -r requirements.txt
```
- 主なレンジ: `langchain>=0.3.0`, `langgraph>=0.1.70`, `langchain-ollama>=0.1.0`, `langchain-openai>=0.2.0`
- Python 3.9+ 必須

## 2) 設定（提案・承認後）
`LLM/config.yaml` に追加:
```yaml
conversation:
  engine: langgraph   # langchain|langgraph（既定: langchain）
  auto_loops: 3       # 既存維持
```

## 3) 起動
```bash
cd LLM
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
- ブラウザ: `http://127.0.0.1:8000/static/`

## 4) 切替/ロールバック
- 切替: `engine=langgraph`
- 退避: `engine=langchain`

## 5) トラブルシュート
- `ChatOllama` が無い: `langchain-ollama` の導入確認（無ければ community へ自動フォールバック）
- 生成が止まる: operation/conversation ログでノード名と相関IDを確認
- 指名不全: 応答末尾の `[Next: INTERNAL_ID]` または `{"next":"INTERNAL_ID"}` を確認
