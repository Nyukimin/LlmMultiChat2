# 次話者指名仕様（v1.0）

## 目的
- LLM応答に含まれる指名タグから、次に会話するキャラクターを確定する手順を定義し、安定かつ決定的に動作させる。

## スコープ
- サーバ側の指名解析・正規化・照合・フォールバック・ロギング
- フロントエンド表示は現状維持（影響なし）

## 用語
- internal_id: `config.yaml` の `characters[].name`（例: `LUMINA`, `CLARIS`, `NOX`）
- display_name: 表示名（日本語。例: `ルミナ`）
- short_name: 短縮記号（例: `る`, `く`, `の`）

## 入力/出力
- 入力: `response_text`（LLM応答、`<think>` 含む場合あり）、`current_speaker_id`、`registry`（キャラ定義）、`policy`（フォールバック/自己指名可否等）
- 出力: `next_speaker_id`（internal_id）と `reason`（`tag`/`round_robin`/`random`/`fuzzy`/`none`）

## 指名タグ形式（許容仕様）
- 推奨（標準）: `[Next: <internal_id>]` 例: `[Next: LUMINA]`
- 互換（寛容受理）:
  - `[Next: <display_name>]` 例: `[Next: ルミナ]`
  - `[Next: <short_name>]` 例: `[Next: る]`
  - 大文字小文字無視、前後空白許容、丸括弧の有無許容（`[Next: (ルミナ)]`）
- 非推奨（将来廃止予定）: 言語混淆・敬称付き（`さん`/`様`/`ちゃん`）

正規表現（抽出）:
- `\[(?:Next|next|NEXT)\s*:\s*([^\]]+)\]`

## 正規化ルール
1. `<think>...</think>` 区画を除去（DOTALL）
2. 引用符/丸括弧/全角半角差/前後空白を正規化（NFKC）
3. 敬称（`さん`/`様`/`ちゃん`）と句読点を除去
4. 大文字化（英字のみ）

## 照合ルール（順序）
1. 完全一致（internal_id）
2. 完全一致（display_name）
3. 完全一致（short_name）
4. シノニム辞書（`registry` から自動生成: 上記の大小・全角半角・括弧抜き・引用抜きの派生）
5. 近似一致（`difflib.get_close_matches`、しきい値: 0.85、対象は internal_id/display_name/short_name）

一致結果が `current_speaker_id` と同一の場合の扱い:
- 既定: 自己指名は無効とし、フォールバックへ
- オプション: `policy.allow_self_nomination = true` で許可

## フォールバック戦略
- `tag` が不在・不明・無効:
  1. `round_robin`（`config.yaml` の並び順で次、自己除外）
  2. `random`（`policy.fallback = random` の場合）
- どちらも不可の場合は `none` を返し自律ループ終了

## ロギング
- `operation` ログに以下をINFOで追記
  - `extracted_raw`（抽出された文字列）
  - `normalized`（正規化後文字列）
  - `matched_id`（最終決定 internal_id）
  - `reason`（`tag`/`fuzzy`/`round_robin`/`random`/`none`）
- 失敗（例外/未決定）はWARNING/ERRORで記録

## 設定（提案）
- `LLM/global_rules.yaml` の文言を強化:
  - 「次の会話者は internal_id（例: `LUMINA`）で `[Next: INTERNAL_ID]` の形式で指名すること」
  - 他参加者を `{other_characters}` で明示し、その中から選ぶこと
- `policy`（コード側・定数/設定化）:
  - `allow_self_nomination` (bool, default=false)
  - `fallback` (enum: `round_robin` | `random`, default=`round_robin`)
  - `fuzzy_threshold` (float, default=0.85)

## 例外・境界条件
- `USER` や未登録IDを指名: 無効→フォールバック
- 複数 `[Next: ...]` がある: 最後に出現したものを採用（最新意図優先）
- display_name が重複: `internal_id` 指名を強く推奨（ユニーク性担保）

## 互換性
- 従来の日本語 display_name 指名を受理（後方互換）
- 将来的に internal_id 指名を標準化

## テスト観点（抜粋）
- 正常: `[Next: LUMINA]` → `LUMINA`
- 日本語: `[Next: ルミナ]` → `LUMINA`
- 短縮: `[Next: る]` → `LUMINA`
- 敬称: `[Next: ルミナさん]` → `LUMINA`
- 括弧: `[Next: (クラリス)]` → `CLARIS`
- 大文字小文字/空白: `[next:   nox ]` → `NOX`
- 自己指名: `[Next: LUMINA]` かつ話者=LUMINA → RR/Randomへ
- タグ欠落: フォールバックへ
- 未登録: フォールバックへ
- 複数タグ: 最後のタグ採用

## 実装インターフェース（案）
```python
@dataclass
class NextPolicy:
    allow_self_nomination: bool = False
    fallback: Literal["round_robin", "random"] = "round_robin"
    fuzzy_threshold: float = 0.85

@dataclass
class CharacterRegistry:
    # internal_id は config.name、display_name/short_name を含む
    members: List[Dict[str, str]]  # {internal_id, display_name, short_name}

Resolved = TypedDict("Resolved", {"next_id": Optional[str], "reason": str, "extracted": str, "normalized": str})

def resolve_next_speaker(response_text: str, current_id: str, registry: CharacterRegistry, policy: NextPolicy) -> Resolved:
    ...  # 上記仕様に従う
```

## 実装計画（段階）
1) `LLM/next_speaker_resolver.py` 追加（抽出/正規化/照合/フォールバック/ロギング）
2) `conversation_loop.py` の `[Next]` 抽出箇所をリプレース（決定理由もログ）
3) `global_rules.yaml` の指示文を internal_id 指定推奨へ強化
4) 単体テスト（主要ケース）

## 非機能要件
- 計算量 O(キャラ数)。正規化/照合は1ミリ秒オーダー（通常）
- 例外は会話を止めず、フォールバックで継続

## セキュリティ/セーフティ
- 未登録IDは常に拒否
- ユーザー/外部文字列による任意のID注入を許可しない

## 将来拡張
- 国際化（多言語 display_name 同時受理）
- システムメッセージとして 
  - `{"type":"control","next":"INTERNAL_ID"}` を併用（LLMによる誤整形の回避）
- 監査用に `decision_log` を別ファイル出力（任意）
