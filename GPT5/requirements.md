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
- core-conversation: `conversation_loop.py`, `next_speaker_resolver.py`, `status_manager.py`, `websocket_manager.py`
- llm-provider: `llm_factory.py`, `llm_instance_manager.py`, `web_search.py`
- memory: `memory_manager.py`
- logging: `log_manager.py`, ルート `logs/` 運用、UI 連携
- kb: `KB/ingest.py`, `init_db.py`, `schema.sql`, `cleanup_dedup.py`, `query.py`, `html/kb/*`
- persona-rules: `persona_manager.py`, `character_manager.py`, `personas.yaml`, `global_rules.yaml`, `user_profile.yaml`
- config-readiness: `LLM/config.yaml`, `KB/config.yaml`, `readiness_checker.py`
- ui-api: WebSocket エンドポイント/ステータス更新/キャラ設定配信
- kb-api: KB の REST エンドポイント
- tests: `LLM/tests/*`

## 6. 制約事項
- OS/シェル: Windows PowerShell。環境操作は `conda activate ChatEnv` 前提（コマンド提示のみ）。
- 承認プロセス: 各ステージ承認後に進行。UI/UX 変更は事前承認必須。
- 環境変更・長時間/外部通信ジョブ・Git 操作は承認があるまで禁止。

## 7. 成功基準
- 会話ループがエラーなく複数ターン実行できる。
- UI でログが表示され、ログディレクトリを `config.yaml` で切替可能。
- KB 取込→検索→表示が期待通り動作。
- ペルソナ/ルールが会話に反映される（検証合格）。
- 主要ユニット/統合テストが合格し、文書（requirements/design/test/tasks）が整備済み。

## 8. リスクと対策
- トークン超過/レイテンシ: タイムアウト、分割生成、ストリーミング/ログで診断。
- DB 肥大/重複: 取込時デデュプリケーション、アーカイブ方針。
- 循環依存: 境界/依存ルールで抑止、静的チェック。
- WebSocket 不安定: 再接続/バックオフ、サーバ側バッファリング。

## 9. 今後の検討
- LangGraph への移行範囲と段階計画。
- LLM/KB プラグイン拡張。
- メトリクス/ダッシュボード。

## 10. 参照
- `docs/SystemOverview.md`, `docs/specification.md`, `docs/*LangGraph*`, `ChatAIMemorySpec.md`
- `LLM/*.py`, `LLM/*.yaml`, `KB/*.py`, `KB/*.sql`, `html/*`

## 11. 設定・データ仕様
- `LLM/config.yaml`
  - `characters[]`: `name`(INTERNAL_ID), `display_name`, `short_name`, `provider`, `model`, `base_url`, `generation{temperature, top_p, repeat_penalty, num_predict}`
  - `logs.conversation_dir` 既定 `LLM/logs`
  - `logs.operation_dir` 既定 `logs`
  - `conversation.auto_loops` 自律会話上限（`global_rules.max_autonomous_turns` を上書き）
  - `kb.ingest_mode`(bool), `kb.db_path`(SQLite), `kb.category_hint`
- `KB/config.yaml`: `max_auto_next`, `db_path`
- `LLM/global_rules.yaml`: `response_constraints`/`flow_rules`/`prompt_template`
- メモリ JSONL: `{session_id, thread_id, ts_start, ts_end, domain, summary, keywords[], embedding, full_log}`

## 12. UI 要件
- WebSocket 受信イベント
  - `message`: `{ speaker, text }` をチャット表示
  - `status`: `{ character, status }` をステータス反映
  - `config`: `{ characters[] }` で表示名→内部名マップ更新
- 送信: ユーザー入力テキスト
- 空応答: 「（応答なし）」表示

## 13. エラーハンドリング要件
- 生成タイムアウト（60s）: ユーザー向け短文、操作ログ WARNING。
- LLM 例外: ユーザー向け短文、操作ログ ERROR。
- WS 送信失敗: 操作ログ ERROR、継続判断は設計。
- メモリ永続化失敗: 操作ログ ERROR、会話継続。

## 14. WebSocket/API 要件
- WS エンドポイント: `/ws`
- 受信: `message/status/config`
- HTML 側: `addMessage`/`updateStatus`/`updateCharacterConfig`

## 15. KB API 要件
- Ingest UI: `POST /api/ingest`, `POST /api/ingest/stop`, `POST /api/kb/init`, `GET /api/suggest`
- Viewer UI: `GET /api/db/works|persons|fts`, `GET /api/db/works/{id}|{id}/cast`, `GET /api/db/persons/{id}|{id}/credits`, `POST /api/kb/cleanup`
- 全レスポンス JSON、エラーも日本語説明を含む。

## 16. DB スキーマ要件
- `category`, `person`, `work`, `credit`, `alias`, `external_id`, `unified_work`, `unified_work_member`, `fts`（FTS5）。
- Insert/Update/Delete で FTS 同期。
- 一意制約/重複抑止を徹底。

## 17. Ingest/Viewer 連携
- Ingest ログは画面で追記・自動スクロール。
- strict 時は厳密 JSON のみ。失敗は UI で明示。
- Cleanup は Dry-run → 本実行の段階確認。

## 18. セキュリティ
- UI/ログに機微を出さない。外部 ID は `source/value/url` のみ。

## 19. KB 自動登録（kbjson）
- 方針: 有効（合意）。AI 応答に含まれる JSON ブロックを自動検出し KB 登録。
- 検出順: `<<<KBJSON_START>>> ... <<<KBJSON_END>>>` → ```json フェンス → 最外 `{...}`。
- タイミング: `process_character_turn` で抽出→正規化→DB 登録（非同期可）。
- エラー: 操作ログ WARNING/ERROR、UI は短文通知で会話継続。
- 許可キー: `persons/works/credits/external_ids/unified` のみ。

## 20. CORS（開発）
- ローカルのみ許可: `http://localhost:*`, `http://127.0.0.1:*`。
- 本番は許可ドメインを列挙。

## 21. ステータス UI（動的生成 1〜5 名）
- `config` 受信で行を再構築（最大 5 名）。固定 ID に依存しない。
- `display_name→name` マップで内部名に解決、`char-state` クラスで状態反映。

## 22. LLM プロバイダ切替
- OpenAI / Gemini / Anthropic / OpenRouter / Ollama を切替可能。
- 認証は環境変数から取得、ログに出さない。タイムアウトは概ね 60s。

## 23. UI ログ表示（タブ切替）
- 方式: Chat / Logs の 2 タブ。既定 Chat。
- Logs には LLM タイムアウト/例外、KB 登録 成否、WS 接続/切断/送信失敗の要点を表示。