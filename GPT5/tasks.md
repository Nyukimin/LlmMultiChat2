# タスクリスト - LlmMultiChat2 実装計画（GPT5）

## 概要
- 対象範囲: 会話制御/KB自動登録/UIログタブ/動的ステータス/CORS制限/LLMプロバイダ拡張/テスト
- 目安: 1〜2週間（個人ペース）
- 優先度: 高=クリティカル経路、中=標準、低=後回し可

## フェーズ1: 準備・設定

### T1: CORS をローカル限定へ変更（優先: 高）
- 作業: `LLM/main.py` の `add_middleware(CORSMiddleware, allow_origins=...)` を localhost/127.0.0.1 のみに列挙
- 完了条件:
  - 非ローカルオリジンからのブラウザアクセスがブロックされる
  - ローカルからは現状どおり動作
- 依存: なし
- 目安: 0.5h

### T2: 設定フラグ確認（優先: 中）
- 作業: `LLM/config.yaml` の `kb.ingest_mode` が既定 false、true で有効になることを確認
- 完了条件:
  - 起動時ログに ingest_mode の有効/無効が分かるINFO出力
- 依存: なし
- 目安: 0.5h

## フェーズ2: バックエンド（会話→KB自動登録）

### T3: kbjson 自動登録の検出/正規化/登録（優先: 高）
- 作業:
  - `conversation_loop.process_character_turn` で応答受領直後に kbjson 抽出
  - 抽出順: `<<<KBJSON_START>>>...END>>>` → ```json フェンス → 最外 `{...}`
  - 正規化: `ingest_mode.py` 相当の `_normalize_extracted_payload` ロジックを共通化/再利用
  - 登録: `KB/ingest.py: ingest_payload(db_path, payload)` をスレッド実行（遅延最小化）
  - UI通知: 成功→「KBに登録しました」/ 失敗→「KB登録に失敗しました」（短文、日本語）を System メッセージでWS送信
  - ログ: 操作ログに件数サマリ/警告/例外
- 完了条件:
  - ingest_mode=true で、応答内 JSON を DB へ登録できる（persons/works/credits 等）
  - 失敗時も会話は継続し、UIへ短文通知
- 依存: T2
- 目安: 3–5h

### T4: KBカテゴリヒントの適用（任意/優先: 低）
- 作業: `LLM/config.yaml: kb.category_hint` を kbjson 登録時に未指定カテゴリへ適用（なければ従来の既定）
- 完了条件: 指定時に `work.category` が補完される
- 依存: T3
- 目安: 1h

## フェーズ3: LLMプロバイダ拡張

### T5: LLMFactory のプロバイダ拡張（優先: 中）
- 作業: `llm_factory.py` に以下のクライアント骨子を追加、`ainvoke(system,user)` 統一
  - OpenAI（既存）、Ollama（既存）、Gemini、Anthropic、OpenRouter
  - APIキーは環境変数から取得、ログへ鍵/生ペイロードは出さない
  - タイムアウト標準化（60s）
- 完了条件:
  - `provider` 切替で呼び出し分岐
  - キー未設定時は安全に失敗し、日本語の短文をUI/詳細は操作ログ
- 依存: なし
- 目安: 4–6h

## フェーズ4: フロントエンド（UI）

### T6: ステータスUIの動的生成（1〜5名）（優先: 高）
- 作業: `html/index.html`/`app.js`
  - `config` 受信時に `status-panel` を再レンダリング（最大5名）
  - `nameMapping`/`statusElements` を再構築、`updateStatus` が反映
  - 6名以上は先頭5名、WARNING を画面ログ＋操作ログ
- 完了条件: 1/3/5名で `status` 反映、`config` 再受信で差し替え
- 依存: なし
- 目安: 2–3h

### T7: ログタブ（Chat/Logs）追加（優先: 高）
- 作業: タブUI（2ボタン/2パネル）。既定 Chat、Logs は `appLog` 出力
- 完了条件: タブ切替・自動スクロール・最低限のスタイル反映
- 依存: なし
- 目安: 2h

### T8: 画面ログへの要点出力（優先: 中）
- 作業: 既存 `appLog(level, message)` を活用し、以下で呼び出し
  - LLM timeout/例外、KB登録 成否、WS 接続/切断/送信失敗
- 完了条件: Logsタブで要点が逐次追記される
- 依存: T7
- 目安: 1h

## フェーズ5: テスト

### T9: 既存テストの維持/補強（優先: 高）
- 作業: `tests/test_next_speaker_resolver.py` の網羅維持
- 目安: 0.5h

### T10: バックエンド単体テスト（優先: 高）
- 作業: モックで `process_character_turn` 正常/timeout/例外/空応答/[Next]/json除去、kbjson 登録フロー
- 目安: 3h

### T11: プロバイダ切替テスト（優先: 中）
- 作業: 各クライアントの成功/timeout/例外、キー未設定、未対応provider
- 目安: 3h

### T12: UI結合テスト（任意/優先: 中）
- 作業: ヘッドレスで `message/status/config` 反映、タブ切替、ログ追記
- 目安: 3h

## フェーズ6: ドキュメント/仕上げ

### T13: 仕様反映と整備（優先: 中）
- 作業: `GPT5/*.md` の最終見直し、I/O例の追補
- 目安: 1h

### T14: textlint（任意/優先: 低）
- 作業: `claude-code-settings`の textlint ルールで `GPT5/*.md` を整形
- 目安: 0.5h

## 実装順序
1) T1 → T3 → T6 → T7 → T8
2) 並行: T5, T10, T11
3) 仕上げ: T2, T4, T9, T12, T13, T14

## リスクと対策
- JSON検出の誤爆: マーカー優先/フェンス優先で誤検出を低減、許可キー以外を破棄
- UI変更の影響: 既存構造を温存し上にタブ/動的生成を重ねる（後方互換）
- プロバイダAPI差異: クライアント層で吸収、`ainvoke` を統一

## 実装開始ガイド
- ブランチ作成→小粒タスクごとにコミット→テスト→ドキュメント更新→PR
- コマンド例（実行はユーザー側・ChatEnv前提）
```powershell
conda activate ChatEnv
# サーバ起動
python -m uvicorn LLM.main:app --reload
# 単体テスト（例）
python -m pytest -q
```