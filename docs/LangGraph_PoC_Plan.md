# LangGraph PoC 計画（最新版）

## 1. 目的
- 既存ループを壊さず並行実装し、設定で切替できることを検証

## 2. スコープ
- `LLM/graph/` の最小構成（state/nodes/app）
- WebSocket I/F 互換（UI無変更）

## 3. 作業項目
- [ ] `LLM/graph/state.py`（State/初期化）
- [ ] `LLM/graph/nodes.py`（prepare/call_llm/postprocess/extract_next/choose_next/send/status/persist）
- [ ] `LLM/graph/app.py`（StateGraph 構築・run）
- （切替フラグは不要。Graph 実装は逐次ループ互換として順次適用）

## 4. 受け入れ条件
- `engine=langgraph` で 3キャラが `auto_loops` 回内で会話し、[Next]/JSON 指名・フォールバックが期待通り動作
- 60s タイムアウト/例外でもループ継続、相関ID付きでログに記録
- 周回終端で JSONL へ要約追記

## 5. テスト
- 単体: ノード入出力（LLM/ログはモック）
- 結合: 指名欠落/自己指名/未登録/複数タグ/空応答
- 疲労: 高頻度入力で安定継続

## 6. マイルストーン
- M1: PoC 実装（1〜2日）
- M2: 機能フラグ切替・結合試験（+1日）
- M3: メモリ統合（+2日）

## 7. リスク/対策
- 依存競合: 互換レンジ固定（`langgraph>=0.1.70`）
- 仕様差: 既存関数をノードで再利用し差分を最小化
- 回帰: ノード単体/結合テストを充実
