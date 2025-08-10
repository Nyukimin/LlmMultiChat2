-- メディア知識ベース スキーマ (SQLite)
PRAGMA foreign_keys=ON;

-- 大分類カテゴリ
CREATE TABLE IF NOT EXISTS category (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,       -- 映画/音楽/小説/漫画/アニメ/ボードゲーム/演劇
  description TEXT
);

-- 人（俳優/声優/監督/作家/スタッフ等）
CREATE TABLE IF NOT EXISTS person (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,              -- 表記名（正規化は別テーブルで吸収）
  kana        TEXT,                       -- 読み（任意）
  birth_year  INTEGER,                    -- 任意
  death_year  INTEGER,                    -- 任意
  note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_person_name ON person(name);

-- 作品（映画/楽曲/アルバム/小説/漫画/アニメ/ボドゲ/演劇 等）
CREATE TABLE IF NOT EXISTS work (
  id           INTEGER PRIMARY KEY,
  category_id  INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  title        TEXT NOT NULL,
  title_kana   TEXT,
  year         INTEGER,                   -- 公開/刊行/初演 年
  subtype      TEXT,                      -- 作品のサブタイプ（映画:劇場/配信 など）
  summary      TEXT
);
CREATE INDEX IF NOT EXISTS idx_work_title ON work(title);
CREATE INDEX IF NOT EXISTS idx_work_cat ON work(category_id);

-- クレジット（人-作品 関係）。出演/監督/原作/作詞/作曲 等の汎用表現
CREATE TABLE IF NOT EXISTS credit (
  id           INTEGER PRIMARY KEY,
  work_id      INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  person_id    INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  role         TEXT NOT NULL,             -- actor/voice/director/author/screenplay... 任意拡張
  character    TEXT,                      -- 役名（俳優/声優時）
  note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_credit_person ON credit(person_id);
CREATE INDEX IF NOT EXISTS idx_credit_work   ON credit(work_id);
CREATE INDEX IF NOT EXISTS idx_credit_role   ON credit(role);

-- 別名・同定（人/作品）
CREATE TABLE IF NOT EXISTS alias (
  id          INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('person','work')),
  entity_id   INTEGER NOT NULL,
  name        TEXT NOT NULL,
  UNIQUE(entity_type, entity_id, name)
);

-- 外部ID（TMDb/IMDb/Wikipedia/公式サイト 等）
CREATE TABLE IF NOT EXISTS external_id (
  id          INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK(entity_type IN ('person','work')),
  entity_id   INTEGER NOT NULL,
  source      TEXT NOT NULL,
  value       TEXT NOT NULL,
  url         TEXT,
  UNIQUE(entity_type, entity_id, source)
);

-- FTS（全文検索）。人名・作品名・要約・役名を検索可能に
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
  kind,          -- 'person' or 'work' or 'credit'
  ref_id,        -- 参照ID
  text,          -- 検索本文
  content=''
);

-- FTS同期トリガ（シンプル版）
CREATE TRIGGER IF NOT EXISTS trg_person_ai AFTER INSERT ON person BEGIN
  INSERT INTO fts(kind, ref_id, text) VALUES ('person', NEW.id, COALESCE(NEW.name,'')||' '||COALESCE(NEW.kana,''));
END;
CREATE TRIGGER IF NOT EXISTS trg_work_ai AFTER INSERT ON work BEGIN
  INSERT INTO fts(kind, ref_id, text) VALUES ('work', NEW.id, COALESCE(NEW.title,'')||' '||COALESCE(NEW.summary,''));
END;
CREATE TRIGGER IF NOT EXISTS trg_credit_ai AFTER INSERT ON credit BEGIN
  INSERT INTO fts(kind, ref_id, text) VALUES ('credit', NEW.id, COALESCE(NEW.character,'')||' '||COALESCE(NEW.role,''));
END;

-- 統合作品（カテゴリ横断の同一題材/シリーズ束ね）
CREATE TABLE IF NOT EXISTS unified_work (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT
);

-- 統合作品 - 個別作品のメンバ関係
CREATE TABLE IF NOT EXISTS unified_work_member (
  id               INTEGER PRIMARY KEY,
  unified_work_id  INTEGER NOT NULL REFERENCES unified_work(id) ON DELETE CASCADE,
  work_id          INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  relation         TEXT NOT NULL, -- original/adaptation/remake/sequel/prequel/etc.
  UNIQUE(unified_work_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_uwm_uw ON unified_work_member(unified_work_id);
CREATE INDEX IF NOT EXISTS idx_uwm_work ON unified_work_member(work_id);