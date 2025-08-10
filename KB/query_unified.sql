-- 統合作品（unified_work）関連の問い合わせ例

-- 1) 作品タイトルから同一題材の全バリアントを取得
WITH target AS (
  SELECT uw.id AS unified_id
  FROM work w
  JOIN unified_work_member uwm ON uwm.work_id=w.id
  JOIN unified_work uw ON uw.id=uwm.unified_work_id
  WHERE w.title LIKE '%国宝%'
  LIMIT 1
)
SELECT w.title, w.year, c.name AS category, uwm.relation
FROM unified_work_member uwm
JOIN work w ON w.id=uwm.work_id
JOIN category c ON c.id=w.category_id
JOIN target t ON t.unified_id=uwm.unified_work_id
ORDER BY w.year, w.title;

-- 2) 人物から同一題材に属する全作品（カテゴリ横断）を取得
WITH person_works AS (
  SELECT DISTINCT w.id
  FROM person p
  JOIN credit c ON c.person_id=p.id
  JOIN work w ON w.id=c.work_id
  WHERE p.name LIKE '%吉沢亮%'
), unified AS (
  SELECT DISTINCT uwm.unified_work_id
  FROM unified_work_member uwm
  WHERE uwm.work_id IN (SELECT id FROM person_works)
)
SELECT w.title, w.year, cat.name AS category, uwm.relation
FROM unified_work_member uwm
JOIN work w ON w.id=uwm.work_id
JOIN category cat ON cat.id=w.category_id
WHERE uwm.unified_work_id IN (SELECT unified_work_id FROM unified)
ORDER BY w.year, w.title;
