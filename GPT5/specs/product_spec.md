# 要件定義書 - LlmMultiChat2 全体仕様（GPT5）

（最終版 2025-08-13）

## 1. 目的
- 複数 LLM とペルソナ/ルールを用いた会話制御、KB（ナレッジベース）連携、ログ可視化、拡張容易性を備えたマルチエージェント会話基盤を提供する。
- 既存資産（`LLM/`, `KB/`, `html/`, `docs/`）を活用し、仕様駆動（Requirements → Design → Test → Tasks）で品質と一貫性を確保する。

## 2. スコープ
- 対象: 会話ループ、発話者決定、メモリ/ログ、LLM接続、KB 取込/検索、Web UI、設定/運用、テスト。
- 非対象（現段階）: クラウド運用設計、CI/CD 最適化、外部課金/認可基盤。

## 3. 機能要件
- 会話制御
  - 会話ループの実行、発話者選定、状態管理、エラー/リトライ。
  - WebSocket によるクライアント更新配信（`message/status/config`）。
  - 応答生成は 60 秒のタイムアウトを持つ。例外/タイムアウトは操作ログへ記録。
  - 応答整形: `<think>...</think>` 除去、前置き削除、2文/160字に短縮、末尾を終止記号で補完。
  - 表示前に `[Next: ...]` と `{"next":"..."}` は削除。空なら「（応答なし）」を表示。
  - 会話履歴を LLM へ供給する際は System を除いた USER/キャラのみ、直近 50 行を採用。
- 次話者決定
  - 優先順: `{"next":"INTERNAL_ID"}` → `[Next: INTERNAL_ID]` → 近似一致（cutoff 0.85）→ ラウンドロビン（未発話優先）。
  - 自己指名は禁止（既定）。
- LLM 接続
  - キャラクター定義に基づき LLM を生成（provider/model/base_url/generation）。
  - REQ/RESP ログに相関 ID（8 桁）、provider/model/base_url、プレビューを記録。
- ペルソナ/ルール
  - `personas.yaml` の `system_prompt` を取得（未定義時は警告ログ）。
  - `global_rules.yaml` の `prompt_template`/`response_constraints`/`flow_rules` を利用。
  - 応答末尾で次話者指名を促進（タグ/JSON のいずれか）。
- メモリ管理
  - 会話サイクル（ユーザー 1 入力→自律ループ）終了時、要約 JSON を `LLM/logs/memory/session_threads.jsonl` に追記（`summary`/`keywords[5]`）。失敗時は末尾数行をフォールバック保存。
- ログ
  - 会話ログ: `LLM/logs/conversation_YYYYmmdd-HHMMSS.log`
  - 操作ログ: `logs/operation_YYYYmmdd-HHMMSS.log`
  - UI でログ可視化（後述のログタブ要件）。
- KB（ナレッジベース）
  - SQLite（既定 `KB/media.db`）。取込（ingest）、重複排除、スキーマ管理、クエリ、閲覧（`html/kb`）。
- Web UI
  - 会話/ログの可視化、KB ビュー（Ingest/Viewer）。
  - エラーは日本語表示、原始レスポンスの露出禁止。
- 構成/運用
  - `LLM/config.yaml` と `KB/config.yaml` による設定管理（ログパス、LLM 種別、閾値）。
- テスト
  - 既存 `LLM/tests/test_next_speaker_resolver.py` を起点に正常/異常/境界値を網羅。

## 4. 非機能要件
- 性能: 1 会話ターン応答 ≤ 10s、KB 検索 ≤ 2s。
- 信頼性: 冪等リトライ、例外通知、機能分離による障害波及抑制。
- 可観測性: 構造化ログ、コンテキスト ID、UI ログ可視化、設定で出力先変更可能。
- 保守性: モジュール化、明確なインターフェース、ドキュメント整備。
- セキュリティ: 機密値は環境/設定からのみ参照。ログ/UI に機微値を出さない。

## 5. モジュール分離方針
- core-conversation, llm-provider, memory, logging, kb, persona-rules, config-readiness, ui-api, kb-api, tests

## 6. 制約事項／7. 成功基準／8. リスク／9. 今後の検討／10. 参照／11-23. 詳細
- 原本 `GPT5/requirements.md` を参照（本ファイルは全文コピー）。
