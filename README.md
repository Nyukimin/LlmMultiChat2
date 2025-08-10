# Multi-Character LLM System

[MIT](https://opensource.org/licenses/MIT)

複数のLLMキャラクター（ルミナ/クラリス/ノクス）が、ユーザーの入力後に自律的に会話を交わすローカル実行基盤です。設定（YAML）を編集するだけで、使用モデルや接続先、会話ルールを切り替えられます。

## 概要 / 特徴
- **LangGraph + FastAPI + WebSocket** で軽量構成（`docs/_index_LangGraph.md` 参照）
- **マルチLLM**（Ollama, OpenAI ほか）をキャラ単位で選択
- **次話者指名**: 応答末尾の `[Next: INTERNAL_ID]`（または `{"next":"INTERNAL_ID"}`）を解析し、話者を決定
- **ログ**: 会話ログと操作ログ。LLM呼び出しは相関ID付き REQ/RESP/TIMEOUT/ERROR を記録
- **会話整形**: 前置き削除 + 最大2文/160字に短縮。空応答も「（応答なし）」で可視化
- **安定化**: LLM呼び出しに60秒タイムアウト、保守的パラメータ（温度など）

## 📁 ディレクトリ
```
.
├── LLM/
│   ├── main.py                 # FastAPIエントリ
│   ├── websocket_manager.py
│   ├── conversation_loop.py    # 会話制御/整形/ループ
│   ├── next_speaker_resolver.py
│   ├── character_manager.py
│   ├── persona_manager.py
│   ├── llm_factory.py          # LLM生成（温度等を抑制）
│   ├── llm_instance_manager.py
│   ├── readiness_checker.py    # 起動時のOllama準備
│   ├── memory_manager.py       # 会話サイクル要約の永続化
│   ├── log_manager.py
│   ├── config.yaml             # 接続/会話ループ設定
│   ├── personas.yaml           # ペルソナ
│   ├── requirements.txt
│   └── logs/                   # 会話ログ（git管理外）
├── html/
│   ├── index.html / app.js / style.css
├── logs/                       # 操作ログ（git管理外）
├── docs/
└── README.md
```

## ⚙️ セットアップ
1) 前提: Python 3.9+、必要に応じて [Ollama](https://ollama.com/) が稼働

2) 依存インストール（主要レンジは `LLM/requirements.txt` を参照: `langgraph>=0.1.70`, `httpx`, `openai` など）
```
cd LLM
pip install -r requirements.txt
```

3) （任意）.env（OpenAI等を使う場合）
```
OPENAI_API_KEY="sk-..."
```

4) モデル準備（Ollama）
```
ollama pull 7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0
```

## 🔧 設定ポイント
`LLM/config.yaml`
```yaml
characters:
  - name: "LUMINA"   # INTERNAL_ID（英字）
    display_name: "ルミナ"
    short_name: "る"
    provider: "ollama"
    model: "7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0"
    base_url: "http://localhost:11434" # 例

  - name: "CLARIS"
    display_name: "クラリス"
    short_name: "く"
    provider: "ollama"
    model: "7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0"

  - name: "NOX"
    display_name: "ノクス"
    short_name: "の"
    provider: "ollama"
    model: "7shi/llm-jp-3-ezo-humanities:3.7b-instruct-q8_0"

logs:
  conversation_dir: "LLM/logs"
  operation_dir: "logs"

conversation:
  # ユーザー1入力ごとに自動で回す最大ターン数（0なら自動会話なし）
  auto_loops: 3
```

`LLM/global_rules.yaml`（抜粋）
- 日本語で手短（2〜3文）
- 思考/メタ情報禁止
- 応答末尾で `[Next: INTERNAL_ID]`（できれば `{\"next\":\"INTERNAL_ID\"}` も）

`LLM/personas.yaml`
- ルミナ/クラリス/ノクスのキャラクター性。クラリスは推測回避・根拠提示を強調

## 🚀 起動
```
cd LLM
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
ブラウザ: `http://127.0.0.1:8000/static/`

## 🔭 ログと可観測性
- 操作ログ: `logs/operation_*.log`
  - 例: `[INFO] [LLMCall] REQ ab12cd34 -> speaker=クラリス, provider=...`
  - 例: `[INFO] [LLMCall] RESP ab12cd34 <- speaker=クラリス, chars=...`
- 会話ログ: `LLM/logs/conversation_*.log`
- `.gitignore` によりログはリポジトリに含まれません

## よくある質問
- 応答が長すぎる/未完に見える → サーバ側で前置き削除+短縮を適用。必要なら `conversation_loop.py` の閾値を調整
- 自動会話が止まる → `conversation.auto_loops` を確認。20 など大きくすると巡回継続します
- OpenAI/Ollama の疎通 → `OPENAI_API_KEY` や `base_url` を確認。Ollamaは `/api/*` の生RESTを利用します

## LangGraph 関連資料
- 設計/移行/PoC/クイックスタートは `docs/_index_LangGraph.md` を参照

## ライセンス
MIT
