# LangGraph 移行計画（最新版）

## 0. 現状整理（2025-08 時点）
- 実装実態
  - 会話制御は `LLM/conversation_loop.py`（LangChain メッセージ）
  - LLM生成は `LLM/llm_factory.py`（`langchain-ollama` 優先、`langchain-community` フォールバック／`langchain-openai`）
  - 次話者決定は `LLM/next_speaker_resolver.py`（タグ/近似/RR/Random）
  - メモリ要約は `LLM/memory_manager.py`（JSONL簡易永続）
- 依存（最新レンジ導入済み）
  - `langchain>=0.3.0`, `langchain-community>=0.3.0`, `langchain-openai>=0.2.0`, `langchain-ollama>=0.1.0`
  - `langgraph>=0.1.70`
  - `fastapi>=0.115.0`, `uvicorn>=0.30.0`, `websockets>=12.0`
- 互換ポリシー
  - `ChatOllama` は `langchain-ollama` を優先。未導入環境では `langchain-community` に自動フォールバック

## 1. 目的
- LangChain 中心の逐次ロジックを LangGraph の StateGraph に段階移行し、状態遷移を明示化
- ノード再利用/テスト容易性/観測性（相関ID・ノード名）を向上
- 短期（state）/中期（JSONL→将来Redis/DuckDB）/長期（VectorDB）のメモリ階層へ拡張可能に

## 2. スコープ/非スコープ
- スコープ: 会話ループの内部制御を Graph 化。WebSocket I/F/フロントは現状維持
- 非スコープ: UI/UXの変更、外部ベンダー追加（別途承認）

## 3. リスクと対策
- 依存衝突: LangChain/Graph の併存 → 互換レンジ固定、機能フラグで切替
- 仕様差分: LLM呼出/短縮/タグ抽出 → 既存関数をノード内で再利用
- タイムアウト: 60s 維持、ノード単位で try/except とフォールバック

## 4. 段階的移行シナリオ
1) PoC 併存（engine 切替）
2) 部分切替（呼出→抽出→選定の中心ループをGraphへ）
3) メモリ統合（周回終端で永続ノードを実行）
4) 既定切替（Graph をデフォルト、旧ループは保守のみ）

## 5. タスクリスト
- 設定/切替
  - [ ] `LLM/config.yaml` に `conversation.engine: langchain|langgraph`（既定: langchain）
  - [ ] `websocket_manager` で分岐実行
- 実装
  - [ ] `LLM/graph/state.py`（State型/初期化）
  - [ ] `LLM/graph/nodes.py`（prepare/call_llm/postprocess/extract_next/choose_next/send/status/persist）
  - [ ] `LLM/graph/app.py`（StateGraph 構築・run）
- 試験
  - [ ] 単体（ノード関数）/結合（3キャラ・分岐・タイムアウト）
  - [ ] 負荷（連続入力・空応答）
- 運用
  - [ ] ロールバック手順（engine=langchain）

## 6. 影響範囲
- コード: `conversation_loop.py`, `memory_manager.py`, `character_manager.py`, `websocket_manager.py`
- 依存: `LLM/requirements.txt` に `langgraph` 追加済み
- ログ: ノード名/相関IDの付与ポイント増

## 7. 承認事項（実施前）
- 設定キー追加（`conversation.engine`）
- Graph ファイル群の新設（`LLM/graph/`）

## 8. ロールバック
- `conversation.engine = langchain` で即時復帰

## 9. マイルストーン（目安）
- M1: PoC（1〜2日）
- M2: 切替β（+1〜2日）
- M3: メモリ統合（+2〜3日）
- M4: 本番切替（+1日）
