# FINAL HANDOFF - LlmMultiChat2 (GPT5)

この資料は、実装に必要な最終仕様と実装手順の要点を一枚に集約したものです。詳細は `product_spec.md`（製品仕様）、`implementation_spec.md`（実装仕様）、`test_spec.md`（テスト仕様）を参照してください。

## 1. 最終仕様（要点）
- 会話制御: 応答60sタイムアウト、think/前置き除去→2文/160字→終止、`message/status/config` をWSで配信
- 次話者決定: JSON `{next}` → `[Next:]` → 近似(0.85) → RR、自己指名禁止
- メモリ: 会話サイクル末に要約JSONを `LLM/logs/memory/session_threads.jsonl` へ追記
- KB: SQLite(`KB/media.db`)。UIに Ingest/Viewer。CleanupはDry-run→本実行
- kbjson自動登録: 有効（`kb.ingest_mode=true`）。抽出順（マーカー→jsonフェンス→最外括弧）、正規化→`KB/ingest.py` 登録。失敗はUI短文+操作ログ。category_hintの自動補完は未実装
- UI: Chat/Logs のタブ切替。Logsに LLM timeout/例外、KB登録 成否、WS接続/切断/送信失敗を要点表示
- ステータス: `config` 受信時に1〜5名を動的生成。6名超は先頭5名＋警告
- CORS（開発）: localhost/127.0.0.1 のみ許可。本番はドメイン列挙
- LLM切替: OpenAI/Gemini/Anthropic/OpenRouter/Ollama に対応。APIキーは環境変数、ログ非出力

## 2. 実装手順（優先順）
1) CORSローカル限定（`LLM/main.py` の `allow_origins` を localhost/127.0.0.1 に）
2) kbjson自動登録（`conversation_loop.process_character_turn` に抽出→正規化→`KB/ingest.py` 登録。UI短文通知/操作ログ）
3) ステータスUI動的生成（`app.js` で `config` 受信時に `status-panel` を再構築、最大5名）
4) Chat/Logsタブ追加（`index.html` と `style.css`、`appLog` をLogsへ出力）
5) 画面ログ出力を要点イベントで呼び出し（timeout/例外/KB登録/WS）
6) LLMFactory拡張（Gemini/Anthropic/OpenRouter クライアント骨子、キーは環境変数、60s timeout）
7) テスト実装（resolver維持、process_character_turn、kbjson、UI結合、プロバイダ切替）

## 3. 設定/鍵
- OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY を環境に設定
- `LLM/config.yaml` の `characters[].provider/model/base_url/generation` を確認
- `kb.ingest_mode=true` で kbjson 自動登録を有効化

## 4. 完了条件
- すべてのテストが合格し、UI で Chat/Logs タブ・動的ステータス・kbjson 自動登録が動作
- 仕様通りのログ/エラーハンドリング/LLM切替が確認できる

## 5. 参照
- 製品仕様: `product_spec.md`
- 実装仕様: `implementation_spec.md`
- テスト仕様: `test_spec.md`
