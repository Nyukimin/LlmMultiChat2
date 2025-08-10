# HOWTO: LLMを追加する

本システムは LangGraph + FastAPI + WebSocket 構成で、LLM呼び出しは HTTP クライアント（Ollama REST / OpenAI API）を利用します。新しい LLM を追加する最短手順と、拡張（独自プロバイダ）の方法をまとめます。

## 1. 既存プロバイダでキャラクターを追加（推奨）
対象ファイル: `LLM/config.yaml`

```yaml
characters:
  - name: "NEWCHAR"
    display_name: "ニューキャラ"
    provider: "ollama"          # または "openai"
    model: "7shi/..."           # ollama のモデル名 or OpenAI のモデル名
    base_url: "http://host:11434"  # ollama の場合は必須（例示）
    generation:                  # 任意（温度など）
      temperature: 0.8
      top_p: 0.95
      repeat_penalty: 1.05
      num_predict: 220
```

- `provider`: `ollama` か `openai`
- `model`: 
  - Ollama: サーバに存在するモデル名（`/api/show` で確認可能）
  - OpenAI: API で利用可能なモデル名
- `base_url`:
  - Ollama: `http://<host>:11434`
  - OpenAI: 通常は不要（プロキシ使用時に設定）
- `generation`: 生成パラメータ（温度を上げると多様性が増します）

保存後、サーバを再起動し、`/ws`接続時に `type=config` に新キャラが含まれることを確認します。

## 2. 認証・前提
- OpenAI を使う場合: `.env` に `OPENAI_API_KEY` を設定
  ```env
  OPENAI_API_KEY=sk-...
  ```
- Ollama を使う場合: サーバ起動時に `ReadinessChecker` がモデルロードを試みます（`LLM/main.py`）。

## 3. 動作確認
- 起動: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`（`LLM/`ディレクトリ）
- ブラウザ: `http://127.0.0.1:8000/static/`
- ログ: `logs/operation_*.log`, `LLM/logs/conversation_*.log`

## 4. 独自プロバイダを追加（拡張）
対象ファイル: `LLM/llm_factory.py`

1) `Async<Provider>NameClient` を追加
```python
class AsyncMyProviderClient:
    def __init__(self, base_url: str, model: str, temperature: float = 0.7, operation_log_filename: str | None = None):
        ...
    async def ainvoke(self, system_prompt: str, user_message: str) -> str:
        # HTTP POST/GETで生成を呼び出し、テキストを返す
        return text
```

2) `LLMFactory.create_llm` に `elif provider_l == "myprovider":` を追加し、上記クライアントを返すようにする。

3) `LLM/config.yaml` の該当キャラで `provider: "myprovider"` を指定。

## 5. トラブルシュート
- 生成が返らない / タイムアウト: `logs/operation_*.log` で `LLMCall` の相関ID（REQ/RESP/TIMEOUT/ERROR）を確認
- Ollama: `base_url` の疎通/モデル存在を確認
- OpenAI: `OPENAI_API_KEY` が設定されているか確認
- 文章が未完: `LLM/global_rules.yaml` と `conversation_loop.py` の整形（末尾補完）を参照
