-- schema_version 1 — SPEC §3-3 の DDL をそのまま。PRAGMA は接続ごとに db.connect() で設定する。
CREATE TABLE workspace (
  id          INTEGER PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,                 -- ^[a-z0-9][a-z0-9-]{0,39}$
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  ai_policy   TEXT NOT NULL DEFAULT 'read_write'
              CHECK (ai_policy IN ('read_write','read_only','hidden')),
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,                        -- ISO 8601 UTC 'YYYY-MM-DDTHH:MM:SSZ'
  archived_at TEXT
);

CREATE TABLE item (
  id           INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  title        TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  body         TEXT NOT NULL DEFAULT '',            -- Markdown
  status       TEXT NOT NULL DEFAULT 'candidate'
               CHECK (status IN ('candidate','doing','waiting_human','waiting_ai','done','hold')),
  priority     TEXT NOT NULL DEFAULT 'normal'
               CHECK (priority IN ('low','normal','high','urgent')),
  owner        TEXT,                                -- 'human' | 'ai:<name>' | NULL
  due          TEXT,                                -- 'YYYY-MM-DD' | NULL
  created_by   TEXT NOT NULL,                       -- author
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  completed_at TEXT,
  sort_order   INTEGER NOT NULL DEFAULT 0           -- 列内の並び（小さいほど上）
);
CREATE INDEX item_ws_status ON item(workspace_id, status, sort_order);
CREATE INDEX item_updated   ON item(updated_at);

CREATE TABLE item_tag (
  item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  tag     TEXT NOT NULL CHECK (tag = lower(tag) AND length(tag) BETWEEN 1 AND 40),
  PRIMARY KEY (item_id, tag)
);
CREATE INDEX item_tag_tag ON item_tag(tag);

CREATE TABLE item_link (
  id      INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  kind    TEXT NOT NULL CHECK (kind IN ('article','task','url')),
  target  TEXT NOT NULL,                            -- '/posts/xxx/' | 't-xxxx' | 'https://...'
  label   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE note (
  id         INTEGER PRIMARY KEY,
  item_id    INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  body       TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 4000),  -- Markdown
  author     TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX note_item ON note(item_id, created_at);

CREATE TABLE event (                                -- 追記のみ。UPDATE/DELETE しない
  id           INTEGER PRIMARY KEY,
  workspace_id INTEGER NOT NULL REFERENCES workspace(id),
  item_id      INTEGER REFERENCES item(id),
  kind         TEXT NOT NULL,
  author       TEXT NOT NULL,
  payload      TEXT NOT NULL DEFAULT '{}',          -- JSON。moved なら {"from":..,"to":..,"reason":..}
  source       TEXT NOT NULL CHECK (source IN ('ui','mcp','rest','import')),
  created_at   TEXT NOT NULL
);
CREATE INDEX event_ws_time   ON event(workspace_id, created_at);
CREATE INDEX event_item_time ON event(item_id, created_at);

CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version VALUES (1);
