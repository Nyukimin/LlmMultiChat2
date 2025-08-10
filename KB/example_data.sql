BEGIN;
INSERT INTO category(name) VALUES
 ('映画'),('音楽'),('小説'),('漫画'),('アニメ'),('ボードゲーム'),('演劇');

-- 人
INSERT INTO person(name) VALUES ('吉沢亮');

-- 作品（例）
INSERT INTO work(category_id, title, year, subtype, summary)
SELECT id, '国宝', 2024, '映画', '（例）吉沢亮が出演する映画のダミーエントリ'
FROM category WHERE name='映画';

-- クレジット
INSERT INTO credit(work_id, person_id, role, character)
VALUES (
  (SELECT id FROM work WHERE title='国宝'),
  (SELECT id FROM person WHERE name='吉沢亮'),
  'actor', NULL
);
COMMIT;
