# テスト設計書 - LlmMultiChat2 全体仕様（GPT5）

（最終版 2025-08-13）

- 原本 `GPT5/test_design.md` の全文コピーです。

## 1. テスト概要
- API/WS の I/O 契約を固定し、UI/サーバの片側変更で破綻しないことを重視。
- 主要パスは日本語 UI メッセージで完結（英語レスポンスの露出を避ける）。

## 2. テストケース設計（抜粋）
- 次話者決定: JSON/タグ/近似/RR/自己指名禁止
- 応答整形: think/前置き除去、2文/160 字、終止補完、タグ/JSON削除
- 会話ループ: auto_loops 上限、未発話者優先、空応答スキップ、memory JSONL 追記
- ログ: ファイル名、履歴整形（System除外、直近 N 行）
- メモリ: JSON 要約、フォールバック、thread_id 増分
- LLM: provider 切替、timeout/例外、キー未設定
- KB取り込み: STRICT→repair→deep、正規化、重複回避、unified
- API: persons/works/fts、詳細と cast/credits、init/cleanup
- UI: message/status/config、動的ステータス（1/3/5 名、6 名警告）、タブ切替、ログ追記

## 3. 実行計画／4. 合格基準／5. 付記
- 原本 `GPT5/test_design.md` を参照（本ファイルは全文コピー）。
