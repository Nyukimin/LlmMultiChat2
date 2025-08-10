# メディアDBの使い方

本DBはSQLite+FTSでローカル動作します。大分類（映画/音楽/小説/漫画/アニメ/ボードゲーム/演劇）をまたいで、人（person）と作品（work）を結ぶクレジット（credit）を正規化し、横断検索を可能にします。

## 前提
- Python 3.9+
- `sqlite3` コマンド（任意。ただしCSV投入やSQL実行に便利）

## 初期化
```bash
python KB/init_db.py
# → KB/media.db が生成されます
```

## サンプル投入（任意）
```bash
sqlite3 KB/media.db ".read KB/example_data.sql"
sqlite3 KB/media.db ".read KB/example_unified.sql"  # 統合作品の例
```

## 代表クエリの実行
```bash
sqlite3 KB/media.db ".read KB/query_examples.sql"
sqlite3 KB/media.db ".read KB/query_unified.sql"
```

## 代表的な操作

### 1) 人を追加
```sql
INSERT INTO person(name, kana, birth_year) VALUES ('吉沢亮', NULL, NULL);
```

### 2) 作品を追加（カテゴリ必須）
```sql
-- カテゴリの追加（初回のみ）
INSERT OR IGNORE INTO category(name) VALUES ('映画');

-- 作品の追加
INSERT INTO work(category_id, title, year, subtype, summary)
SELECT id, '国宝', 2024, '映画', '説明'
FROM category WHERE name='映画';
```

### 3) クレジット（出演/監督など）を追加
```sql
INSERT INTO credit(work_id, person_id, role, character)
VALUES (
  (SELECT id FROM work WHERE title='国宝'),
  (SELECT id FROM person WHERE name='吉沢亮'),
  'actor', NULL
);
```

### 4) 別名/外部IDを追加
```sql
INSERT INTO alias(entity_type, entity_id, name)
VALUES ('person', (SELECT id FROM person WHERE name='吉沢亮'), 'Yoshizawa Ryo');

INSERT INTO external_id(entity_type, entity_id, source, value, url)
VALUES ('work', (SELECT id FROM work WHERE title='国宝'), 'wikipedia', '国宝_(映画)', 'https://...');
```

### 5) 統合作品でカテゴリ横断の同一題材を束ねる
```sql
INSERT OR IGNORE INTO unified_work(name, description)
VALUES ('国宝', '同一題材の各カテゴリ作品を束ねる');

INSERT INTO unified_work_member(unified_work_id, work_id, relation)
VALUES ((SELECT id FROM unified_work WHERE name='国宝'),
        (SELECT id FROM work WHERE title='国宝'),
        'adaptation');
```

## 横断検索（FTS）
```sql
SELECT kind, ref_id, snippet(fts, 1, '[', ']', '...', 10)
FROM fts
WHERE fts MATCH '吉沢* OR 国宝*'
LIMIT 50;
```

## CLI（簡易）
```bash
python KB/query.py person "吉沢亮"   # → 人→全出演作
python KB/query.py work   "国宝"     # → 作品→全出演者
```

## Ingest Mode（DB登録専用モード）
LLM同士の協調で事実をJSON抽出し、`KB/media.db`へ自動登録します。

### 実行
```bash
# 依存インストール（未実施なら）
pip install -r LLM/requirements.txt

# DB初期化
python KB/init_db.py

# 映画ドメインで2巡収集し登録（関連語をシードに拡張）
python LLM/ingest_main.py "吉沢亮 国宝" --domain 映画 --rounds 2 --db KB/media.db
```

### JSONスキーマ（抜粋）
```json
{
  "persons": [{ "name": "", "aliases": [""] }],
  "works": [{ "title": "", "category": "映画", "year": 2024, "subtype": null, "summary": null }],
  "credits": [{ "work": "", "person": "", "role": "actor", "character": null }],
  "external_ids": [{ "entity": "work", "name": "", "source": "wikipedia", "value": "", "url": null }],
  "unified": [{ "name": "国宝", "work": "国宝", "relation": "adaptation" }],
  "note": null
}
```

### ログと確認
- 会話ログ: `LLM/logs/ingest_conversation.log`
- 操作ログ: `logs/operation_ingest.log`
- 登録確認:
  ```bash
  python KB/query.py work "国宝"
  python KB/query.py person "吉沢亮"
  sqlite3 KB/media.db ".read KB/query_unified.sql"
  ```

## CSV投入（任意）
`sqlite3` を使い、CSVを直接テーブルへ投入できます。
```bash
sqlite3 KB/media.db ".mode csv"
sqlite3 KB/media.db ".import path/to/person.csv person"
```

## 入力キーと意味（テーブル別まとめ）

以下は主要テーブルに投入する際のカラム一覧と意味です（NULL可は任意）。

### category
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| name | TEXT | 必須 | 大分類名（映画/音楽/小説/漫画/アニメ/ボードゲーム/演劇） |
| description | TEXT | 任意 | 説明 |

### person（人物）
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| name | TEXT | 必須 | 表記名 |
| kana | TEXT | 任意 | 読み（かな等） |
| birth_year | INTEGER | 任意 | 生年 |
| death_year | INTEGER | 任意 | 没年 |
| note | TEXT | 任意 | 備考 |

### work（作品）
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| category_id | INTEGER | 必須 | 紐づく`category.id` |
| title | TEXT | 必須 | 作品名 |
| title_kana | TEXT | 任意 | 読み |
| year | INTEGER | 任意 | 公開/刊行/初演年 |
| subtype | TEXT | 任意 | サブタイプ（例: 映画=劇場/配信、音楽=アルバム/シングル など） |
| summary | TEXT | 任意 | 要約 |

### credit（クレジット：人×作品）
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| work_id | INTEGER | 必須 | `work.id` |
| person_id | INTEGER | 必須 | `person.id` |
| role | TEXT | 必須 | 役割（例: actor/voice/director/author/screenplay/producer/composer 等） |
| character | TEXT | 任意 | 役名（俳優/声優など） |
| note | TEXT | 任意 | 備考 |

推奨`role`値例: actor（俳優）, voice（声優）, director（監督）, author（原作/著者）, screenplay（脚本）, composer（作曲）, lyricist（作詞）など。必要に応じて拡張可。

### alias（別名）
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| entity_type | TEXT | 必須 | 'person' または 'work' |
| entity_id | INTEGER | 必須 | 対象のID（person.id or work.id） |
| name | TEXT | 必須 | 別名/別表記 |

### external_id（外部ID）
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| entity_type | TEXT | 必須 | 'person' または 'work' |
| entity_id | INTEGER | 必須 | 対象のID（person.id or work.id） |
| source | TEXT | 必須 | ソース（tmdb/imdb/wikipedia/official 等） |
| value | TEXT | 必須 | 識別子（例: TMDb ID, Wikipedia ページ名） |
| url | TEXT | 任意 | 参照URL |

### unified_work（統合作品）
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| name | TEXT | 必須 | 題材名/シリーズ名（例: 国宝） |
| description | TEXT | 任意 | 説明 |

### unified_work_member（統合作品メンバ）
| カラム | 型 | 必須 | 説明 |
|---|---|---|---|
| unified_work_id | INTEGER | 必須 | `unified_work.id` |
| work_id | INTEGER | 必須 | `work.id` |
| relation | TEXT | 必須 | 関係（original/adaptation/remake/sequel/prequel 等） |

備考:
- 文字列の正規化（全角/半角、別表記）は `alias` の併用を推奨。
- FTSは`person.name/kana`、`work.title/summary`、`credit.character/role`を自動索引します（INSERT時トリガ）。

## よくある質問
- 同一人物が映画/音楽/ドラマに跨る場合？
  - `person`はグローバル一意なので、クレジットを通じてカテゴリ横断で紐づきます。
- 原作と映画/ドラマをまとめたい？
  - `unified_work`/`unified_work_member` を使って題材単位に束ね、横断参照が可能です。
