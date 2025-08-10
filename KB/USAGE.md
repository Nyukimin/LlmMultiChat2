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

## CSV投入（任意）
`sqlite3` を使い、CSVを直接テーブルへ投入できます。
```bash
sqlite3 KB/media.db ".mode csv"
sqlite3 KB/media.db ".import path/to/person.csv person"
```

## よくある質問
- 同一人物が映画/音楽/ドラマに跨る場合？
  - `person`はグローバル一意なので、クレジットを通じてカテゴリ横断で紐づきます。
- 原作と映画/ドラマをまとめたい？
  - `unified_work`/`unified_work_member` を使って題材単位に束ね、横断参照が可能です。
