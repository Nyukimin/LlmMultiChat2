# LangGraph 移行マッピング（最新版）

## 1. ファイル/責務の対応
- `LLM/conversation_loop.py`
  - 置換: `LLM/graph/app.py`（Graph 実行）
  - 分割: prepare → call_llm → postprocess → extract_next → choose_next → send_message → persist_memory
- `LLM/next_speaker_resolver.py`
  - 再利用: `extract_next` ノードで呼び出し
- `LLM/llm_factory.py` / `LLM/llm_instance_manager.py`
  - 再利用: `call_llm` ノードで LLM を取得（Ollama REST / OpenAI API）
- `LLM/character_manager.py` / `LLM/persona_manager.py`
  - 再利用: `prepare_context` ノード
- `LLM/status_manager.py`
  - 再利用: `update_status_*` と送信
- `LLM/memory_manager.py`
  - 再利用: `persist_memory` ノード（周回終端）
- `LLM/log_manager.py`
  - 再利用: ノード境界で操作/会話ログ

## 2. 設定
- `LLM/config.yaml`
  - `conversation.auto_loops` → `max_turns`

## 3. データフロー（要約）
1) prepare_context
2) call_llm（60s）
3) postprocess_response
4) send_message
5) extract_next（`resolve_next_speaker`）
6) choose_next_fallback（RR/Random）
7) end_or_continue
8) persist_memory（終了時）

## 4. ロールバック
（ロールバックは不要。Graph 実装は既存ループ互換のため切替なしで動作）

## 5. 試験観点
- 正常: 3キャラが指名に従い遷移
- 欠落: タグ無/自己指名→フォールバック
- エラー: timeout/例外→継続・ログ
- 表示: `[Next]`/JSON断片を除去
- 永続: JSONL追記
