# 変更履歴（最新: 2025-08-10）

以下はユーザー向けの要点のみをまとめた更新記録です。技術的なpushログは含みません。

## 変更概要
- LangChain依存の排除とLangGraph+HTTPクライアント方針へ移行
- 会話品質向上（ユーザー宛て・完結文）
- 生成パラメータ（温度など）をキャラ別に設定可能化
- HOWTOドキュメント追加
- ルール/ペルソナの強化

## 主な変更
- コア
  - `LLM/llm_factory.py`: LangChain撤去。`AsyncOllamaClient`（/api/generate）・`AsyncOpenAIChatClient`（Chat Completions）を実装。`create_llm(..., gen_params)`で温度等を反映
  - `LLM/conversation_loop.py`: LangChainメッセージ削除。`ainvoke(system, user)`呼出に変更。整形で前置き除去・短縮・末尾補完（未完文防止）
  - `LLM/memory_manager.py`: LC依存削除。要約はJSON出力をパース（Embeddingは将来API化）
  - `LLM/llm_instance_manager.py`: `gen_params`伝播
  - `LLM/character_manager.py`: `characters[].generation`を読み取り、工場へ渡す
- 依存
  - `LLM/requirements.txt`: LangChain系削除、`langgraph`/`httpx`/`openai`を採用
- 設定/ルール
  - `LLM/config.yaml`: 各キャラに`generation`（temperature=0.8, top_p=0.95, repeat_penalty=1.05, num_predict=220）を追加
  - `LLM/global_rules.yaml`: 「常にユーザー宛て」「完結文」を明記。思考補助/問題解決の手順を追記
- ペルソナ
  - `LLM/personas.yaml`: LUMINAに関係性・名前由来を追記。CLARIS/NOXに各思考スタイルを追記
- ドキュメント
  - `docs/*LangGraph*.md`: 設計/移行/マッピング/PoC/クイックスタートを最新化
  - `docs/HOWTO_Add_LLM.md`, `docs/HOWTO_Extend_Rules.md` 追加
  - `README.md`, `docs/SystemOverview.md` をLangGraph+HTTP方針に更新

## 影響/互換性
- WebSocketスキーマは不変。UI変更なし
- 次話者指名仕様（[Next]）は従来通り
- 文章の未完出力が抑制され、ユーザー宛て応答が強化

## 運用メモ
- OpenAI利用時は `.env` に `OPENAI_API_KEY` を設定
- Ollamaは `base_url` を設定（疎通/モデル存在確認）

## 今後
- `LLM/graph/` のGraph実装（State/Nodes）追加
- EmbeddingのAPI直叩き化
- ルール違反検知（他AI宛て呼称）と自動リライトの導入検討
