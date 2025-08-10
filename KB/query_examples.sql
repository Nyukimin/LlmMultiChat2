-- 代表問い合わせ
-- 1) 人→出演作一覧
SELECT w.title, w.year, c.role, c.character
FROM person p
JOIN credit c ON c.person_id=p.id
JOIN work w ON w.id=c.work_id
WHERE p.name LIKE '%吉沢亮%'
ORDER BY w.year, w.title;

-- 2) 作品→出演者一覧
SELECT p.name, c.role, c.character
FROM work w
JOIN credit c ON c.work_id=w.id
JOIN person p ON p.id=c.person_id
WHERE w.title LIKE '%国宝%'
ORDER BY CASE c.role WHEN 'director' THEN 0 WHEN 'actor' THEN 1 ELSE 9 END, p.name;

-- 3) FTSで人/作品/役名を横断検索
SELECT kind, ref_id, snippet(fts, 1, '[', ']', '...', 10)
FROM fts
WHERE fts MATCH '吉沢* OR 国宝*'
LIMIT 50;
