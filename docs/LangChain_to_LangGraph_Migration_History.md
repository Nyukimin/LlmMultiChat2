# LangChain → LangGraph 移行の経緯（履歴・学び）

## 背景
- 初期実装は **LangChain** を用いた逐次会話制御（`SystemMessage/HumanMessage/AIMessage`、`ChatOllama`/`ChatOpenAI`）でした。
- 次話者指名仕様（`[Next: INTERNAL_ID]`）や WebSocket UI との互換は維持しつつ、
  - 状態遷移の明示化（将来的にGraph化）
  - 依存の軽量化・ロックイン回避
  - 可観測性/テスト性/フォールバックの明確化
  を目的に、LangGraphベースへの移行を計画しました。

## 目的
- 会話制御の“手続き + 暗黙の状態”から、“状態遷移の明示（StateGraph）”へ段階的移行。
- LangChain 依存を削り、HTTPクライアント（Ollama REST / OpenAI API）を直接利用。
- UI/WSスキーマや次話者指名仕様の完全互換を維持。

## 段階（ロードマップ）
1. 準備（完了）
   - ドキュメントとタスク整理（`docs/_index_LangGraph.md` ほか）
   - 依存の最新化と互換レンジ明記
2. 依存削減（完了）
   - LangChain のコード依存を排除（HTTPクライアント化）
3. Graph化（未実装／次フェーズ）
   - `LLM/graph/` に State/Nodes を実装し、逐次ループと同等の分岐・フォールバックをGraphで表現
4. 最適化（未実装／次フェーズ）
   - ノード単位の再利用・テスト強化・メモリ階層統合

## 実施内容（主要変更）
- 依存
  - `LLM/requirements.txt`: LangChain系を削除し、`langgraph`, `httpx`, `openai` を採用
- LLM接続
  - `LLM/llm_factory.py`: 
    - 新規 `AsyncOllamaClient`（/api/generate 直叩き）
    - 新規 `AsyncOpenAIChatClient`（Chat Completions 直叩き）
    - 既存 `LLMFactory` は上記クライアントを返す構成へ置換
- 会話制御
  - `LLM/conversation_loop.py`:
    - LangChainメッセージ依存を削除
    - `llm.ainvoke(system_prompt, user_message)` で非同期呼出（60s timeout維持）
    - 既存の短縮/前置き除去/タグ抽出/フォールバックの仕様を維持
- メモリ
  - `LLM/memory_manager.py`:
    - LangChainの`SystemMessage`/Embeddings依存を削除
    - 要約はLLMのJSON出力を解析（失敗時フォールバック）
    - Embeddingは将来のAPI直叩きへ置換予定（現時点は未実装）
- ドキュメント/README
  - LangGraph前提に刷新。切替フラグの概念は撤廃（LangChain非依存のため）
  - SystemOverview を HTTPクライアント + LangGraph オーケストレーション方針へ更新

## 技術的差分（Before/After）
- LLM呼出
  - Before: LangChain `ChatOllama/ChatOpenAI` に `messages` を渡す
  - After: HTTPクライアントに `system_prompt + user_message` を直渡し
- 依存
  - Before: `langchain`, `langchain-community`, `langchain-openai` ほか
  - After: `langgraph`, `httpx`, `openai`（将来Graphをコードで利用）
- メモリ要約
  - Before: LCメッセージ + Embeddings（任意）
  - After: JSON出力をパース（Embeddingは将来APIへ）

## 互換性と可観測性
- WebSocketスキーマ（`type=config|message|status`）は変更なし
- 次話者指名仕様（`[Next: ...]` / `{ "next": "..." }`）は完全互換
- 相関ID（REQ/RESP）とタイムアウト/例外ログは維持

## リスク/対策
- API仕様差分（Ollama/OpenAI）
  - リトライ/タイムアウト・例外処理を統一
- JSON出力破損
  - フォールバック要約（末尾抽出）で継続
- 依存競合
  - LC系を排除し、最小依存に整理

## 検証（抜粋）
- 3キャラ・複数ターンでの自律会話動作
- `[Next]` 欠落/自己指名時のフォールバック（RR/Random）
- タイムアウト/例外時にループ継続・ログ出力

## 未対応/今後
- Graph実装（State/Nodes/Edges）
- Embedding のAPI直叩き化
- `LLM/graph/` 配下の単体・結合テスト整備

## 学び/ベストプラクティス
- 依存段階化：まず“依存削減→Graph化”の順でリスクを小さくする
- 互換維持：UI/WSスキーマ・会話ルールを固定し、内部のみ差し替え
- 観測性：相関IDとログ軸を先に通すと回帰の切り分けが容易

## 主要コミット（抜粋）
- docs(langgraph)… 設計/移行/マッピング/PoC/クイックスタート追加（`fe40252`）
- feat(core)… LangChain除去、HTTPクライアント導入、逐次ループ/メモリ刷新（`2e55572`）
- refactor… コード/ドキュメントからLangChain表記を一掃（`42116ca`）

## 参照
- `README.md`
- `docs/_index_LangGraph.md`
- `docs/LangGraph_Design.md`
- `docs/LangGraph_Mapping.md`
- `docs/LangGraph_Migration.md`
- `docs/LangGraph_PoC_Plan.md`
