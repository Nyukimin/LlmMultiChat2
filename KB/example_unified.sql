BEGIN;
-- 国宝を統合作品に束ねる（例）
INSERT OR IGNORE INTO unified_work(name, description) VALUES ('国宝', '同一題材の各カテゴリ作品を束ねる');
INSERT INTO unified_work_member(unified_work_id, work_id, relation)
VALUES (
  (SELECT id FROM unified_work WHERE name='国宝'),
  (SELECT id FROM work WHERE title='国宝'),
  'adaptation'
);
COMMIT;
