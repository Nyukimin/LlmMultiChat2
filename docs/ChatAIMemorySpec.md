以下のように、**キャラ単位LoRA＋ユーザー別VectorDB参照** を組み込んだ最新仕様に書き換えました。

---

# 3キャラ会話システム – メモリ階層 最新仕様

## 1. メモリ階層とストア

| 階層        | 保存先                               | TTL          | 主目的                          |
| --------- | --------------------------------- | ------------ | ---------------------------- |
| **短期記憶**  | LangGraph `state` (RAM)           | 6～8ターン       | 現在のスレッド（文脈維持）                |
| **中期記憶**  | Redis（24h, ホット）→ DuckDB（7d, ウォーム） | 24h～7日       | セッション継続・割り込み復帰・KPIログ         |
| **長期記憶**  | VectorDB `user:<uid>` + MetaDB    | 無期限          | ユーザープロファイル・嗜好・過去スレッド要約・KPI履歴 |
| **知識ベース** | VectorDB `kb:<domain>`            | ETL随時        | 映画・歴史・ゴシップ等の専門知識             |
| **キャラ成長** | LoRA（キャラ単位で共通）                    | 定期更新（例: 月1回） | キャラが会話を通じて成長し、性格・口調・知識を自然に反映 |

---

## 2. 短期（1スレッド）

* **定義:** 「同一トピックの会話（ユーザー＋3キャラ）」を1スレッドとして扱う
* **構造（RAM）:**

```json
{
  "thread_id": 42,
  "domain": "movie",
  "turns": [ {"speaker": "user", "msg": "..."}, ... ],
  "targets": ["lumina"],
  "ct": { "lumina": 0, "claris": 1, "nox": 0 },
  "auto_prompt": 1
}
```

* スレッド終了時に **要約＋キーワード＋Embedding** を生成し中期へ移動

---

## 3. 中期（セッション記録）

### Redis（ホット）

```makefile
sess:<session_id> → history / agenda / targets / last_thread_id
TTL: 24h
```

### DuckDB（ウォーム）

```sql
CREATE TABLE session_thread (
  thread_id INT,
  session_id TEXT,
  ts_start TIMESTAMP,
  ts_end TIMESTAMP,
  domain TEXT,
  summary TEXT,
  keywords TEXT[],
  embedding VECTOR(768),
  full_log TEXT
);
```

* TTL失効後、ワーカーがDuckDBに移動（週単位で全文保持）

---

## 4. 長期（ユーザー記憶）

### VectorDB

* Namespace: `user:<uid>`
* Embedding＋メタ情報で類似検索

### MetaDB

* thread起源・タイムスタンプ・KPIタグを保持
* 週次で古い低KPIチャンクを整理

---

## 5. 知識ベース

* 名前空間：`kb:movie` / `kb:history` / `kb:gossip`
* 更新頻度：映画＝週次、歴史＝月次、ゴシップ＝毎日
* ETLでデータを取得 → 正規化 → Embedding → VectorDB格納

---

## 6. 長期全文保持ポリシー

* **A案:** 要約のみ永続（全文は削除）
* **B案:** フルログをS3/MinIOに圧縮アーカイブ
* → 現時点では **DuckDBで7日間は全文保持**、その後アーカイブ方式を検討

---

## 7. キャラ・ユーザー成長

* **キャラ成長:**

  * キャラごとに共通LoRAを持つ
  * KPIが一定値を超えた段階で、過去会話データからコーパス抽出
  * LoRA微調整（例：月1回）で性格・知識をアップデート
* **ユーザー記憶:**

  * KPI・プロファイルをVectorDBに蓄積し、パーソナライズ応答
* **KPI管理:**

  * DuckDB/SQLiteで集計
  * `level = floor(sqrt(total_kpi / 10))` で成長度を算出

---
