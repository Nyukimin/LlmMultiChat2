# LangGraph 設計（最新版）

## 1. 方針
- 既存の逐次ロジックを LangGraph StateGraph へ移管し、状態遷移・例外系・フォールバックを明示化
- WebSocket スキーマ/UI は互換維持（変更禁止）
- LLM 接続は既存 `LLMFactory` を再利用（Ollama REST / OpenAI API）

## 2. 依存/要件
- Python: 3.9+
- 主要依存（導入済み）
  - `langgraph>=0.1.70`
  - `fastapi>=0.115.0`, `uvicorn>=0.30.0`, `websockets>=12.0`

## 3. State スキーマ（案）
```python
State = {
  "user_input": str | None,
  "current_display_name": str,
  "current_internal_id": str,
  "registry": list[dict],                # {internal_id, display_name, short_name}
  "spoken_set": set[str],                # display_name
  "turn_index": int,
  "max_turns": int,
  "persona_prompt": str,
  "global_rules": dict,
  "conversation_log_text": str,
  "request_id": str,
  "last_response_text": str | None,
  "display_text": str | None,
  "next_internal_id": str | None,
  "decision_reason": str | None,        # tag|fuzzy|round_robin|random|none
  "error": str | None,
  # I/O
  "websocket": Any,
  "manager": Any,
  "log_filename": str,
  "operation_log_filename": str,
}
```

## 4. ノード
- prepare_context: レジストリ/ルール/履歴/ペルソナ収集→プロンプト合成
- update_status_{thinking|idle|active}: `status_manager` 再利用
- call_llm: `LLMFactory` 取得→60s timeout→REQ/RESP ログ
- postprocess_response: `<think>` 除去/挨拶除去/短縮、UI用テキスト生成
- send_message: `type=message` 送信
- extract_next: `[Next]`/`{"next":""}` 抽出→`resolve_next_speaker`
- choose_next_fallback: RR/Random
- end_or_continue: 継続判定
- persist_memory: 周回終端で `memory_manager.persist_thread_from_log`

## 5. エッジ（例）
- prepare_context → update_status_thinking → call_llm
- call_llm → postprocess_response（成功）／choose_next_fallback（例外/timeout）
- postprocess_response → send_message → extract_next
- extract_next → end_or_continue（決定）／choose_next_fallback（未決/自己指名）
- end_or_continue → update_status_idle（継続）／persist_memory → update_status_active（終了）

## 6. 例外/タイムアウト
- 各ノードで try/except、`error` を state へ格納しフォールバック経路へ
- LLM の 60s タイムアウトを維持

## 7. ログ/可観測性
- `log_manager` を継続。ノード名・相関IDを INFO で記録

## 8. 設定（承認後反映）
- `LLM/config.yaml`
  - `conversation.auto_loops`: 既存

## 9. 互換性
- WebSocket スキーマ・UI・短縮/挨拶除去・[Next]仕様は既存通り
  
