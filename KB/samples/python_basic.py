from KB import api as kb
import sqlite3


def main() -> None:
    # 1) 初期化（バックアップ3件保持）
    res = kb.init_db(reset=True)
    print("init:", res.get("ok"), res.get("stats"))

    # 2) 最小データ投入（映画カテゴリ/人物/作品/クレジット）
    path = kb.resolve_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT OR IGNORE INTO category(name) VALUES ('映画')")
        conn.execute("INSERT OR IGNORE INTO person(name) VALUES ('吉沢亮')")
        conn.execute(
            """
            INSERT INTO work(category_id, title, year)
            SELECT id, '国宝', 2025 FROM category WHERE name='映画'
            ON CONFLICT DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO credit(work_id, person_id, role)
            SELECT w.id, p.id, 'actor'
            FROM work w, person p
            WHERE w.title='国宝' AND p.name='吉沢亮'
            ON CONFLICT DO NOTHING
            """
        )
        conn.commit()

    # 3) 参照API（Python）
    people = kb.persons_search("吉沢")
    print("people:", people)
    if people:
        pid = people[0]["id"]
        print("person_detail:", kb.person_detail(pid))
        print("person_credits:", kb.person_credits(pid)[:3])

    works = kb.works_search("国宝")
    print("works:", works)
    if works:
        wid = works[0]["id"]
        print("work_detail:", kb.work_detail(wid))
        print("work_cast:", kb.work_cast(wid))


if __name__ == "__main__":
    main()


