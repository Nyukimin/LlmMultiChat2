# 詳細設計書 - LlmMultiChat2 全体仕様（GPT5）

（最終版 2025-08-13）

- 原本 `GPT5/design.md` の全文コピーです。

## 1. 追加の設計確定事項
- ログ表示はUI必須（in-app console と画面メッセージ）。接続断・送信失敗・LLMエラーは日本語で即通知。
- DBスキーマは `KB/schema.sql` に固定。cleanupは API により Dry-run→本実行の順でUIから制御。
- WebSocket契約（`message/status/config`）は固定。`config` 受信で `display_name→name` マップを毎回再構築。
- LLM呼出しは `provider` により Ollama/OpenAI を自動選択。生成パラメータは `generation` を優先。

## 2. 既知の境界/例外処理
- 生成が空文字/空白のみ → UI へ「（応答なし）」送信。
- `[Next:]`/`{"next":}` の混入 → 表示前に除去。Resolverは元テキストから抽出に使用。
- WebSocket送信例外 → オペログ ERROR + 継続可否は上位ハンドリング（ループを極力維持）。
- メモリ永続化失敗 → オペログ ERROR、会話は継続。

## 3. 実装ToDo（設計反映のための具体作業提案）
- UI: 画面内の「ログ表示パネル」を設計に沿って拡張（任意）。最低限、エラーと接続状態は表示済み。
- テスト: `process_character_turn` をモック化して timeout/例外/空応答を検証。
- ドキュメント: KB API の入出力例を `GPT5/README.md` に索引用として集約（任意）。

## 4. 品質ゲート
- 既存ユニットテストに加え、WSモック・LLMモック・ingestの3系統テストを追加し、グリーン後に次工程へ。
- textlint により `GPT5/*.md` を整形（ユーザー承認後、実行コマンド提示）。

## 5. KB自動登録（kbjson）設計
- 概要: 会話応答中のJSONブロックを自動抽出し、KBへ登録する。
- 有効化条件: `LLM/config.yaml: kb.ingest_mode = true`
- 抽出順序: (1) `<<<KBJSON_START>>> ... <<<KBJSON_END>>>` → (2) ```json フェンス内の最外 `{...}` → (3) テキスト全体の最初の `{`〜最後の `}`
- 正規化: 既存関数群（`_normalize_extracted_payload` 同等ロジック）で役割語/余剰キー除去
- 登録: `KB/ingest.py: ingest_payload(db_path, payload)` を非同期スレッドで実行（会話遅延を避ける）
- エラー: 操作ログに WARNING/ERROR。UIへ短い日本語メッセージ（例: "KB登録に失敗しました"）
- セキュリティ: 許可キー以外は破棄。URL/外部IDのみ受理。トークン等の機微値は無視。

## 6. UI通知
- 成功: "KBに登録しました"（件数サマリがあれば併記）
- 失敗: "KB登録に失敗しました"（詳細は操作ログ参照）

## 7. テスト項目（抜粋）
- マーカー/フェンス/最外括弧の各パターンで登録成功
- 壊れJSONは repair不可なら警告ログ + 会話継続
- 許可キー外は破棄

## 8. UIログ表示（会話＋操作ログ要点）
- パネル: タブ方式（Chat/Logs）。Logs に要点追記（appLog）。

## 9. ステータスUIの動的生成（1〜5名）
- `config` 受信時に再構築、最大5名。6名超は先頭5名＋WARNING。

## 10. CORS（開発）
- ローカルのみ許可（localhost/127.0.0.1）。本番はドメイン列挙。

## 11. LLMプロバイダ拡張
- OpenAI/Gemini/Anthropic/OpenRouter/Ollama を `provider` で切替。APIキーは環境変数。
