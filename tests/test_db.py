"""DDL・PRAGMA・マイグレーション・バックアップ（SPEC §3-3 / §6-3）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from taskboard import db


def test_init_creates_schema_and_pragmas(db_path: Path):
    conn = db.init_db(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"workspace", "item", "item_tag", "item_link", "note", "event", "schema_version"} <= tables
        assert db.current_version(conn) == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        # 2 回目は何も適用しない（前方のみ・冪等）
        assert db.migrate(conn) == []
    finally:
        conn.close()


def test_check_constraints_reject_bad_values(conn: sqlite3.Connection):
    ws_id = conn.execute("SELECT id FROM workspace LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO item (workspace_id, title, status, created_by, created_at, updated_at) VALUES (?, 'x', 'flying', 'human', 't', 't')",
            (ws_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):  # title 空
        conn.execute(
            "INSERT INTO item (workspace_id, title, created_by, created_at, updated_at) VALUES (?, '', 'human', 't', 't')", (ws_id,)
        )
    with pytest.raises(sqlite3.IntegrityError):  # 外部キー
        conn.execute("INSERT INTO item (workspace_id, title, created_by, created_at, updated_at) VALUES (9999, 'x', 'human', 't', 't')")
    with pytest.raises(sqlite3.IntegrityError):  # event.source
        conn.execute(
            "INSERT INTO event (workspace_id, kind, author, source, created_at) VALUES (?, 'item.created', 'human', 'email', 't')", (ws_id,)
        )


def test_backup_and_prune(db_path: Path, conn: sqlite3.Connection):
    dest1 = db.backup(db_path, keep=2)
    assert dest1.exists() and dest1.parent == db_path.parent / "backups"
    dest2 = db.backup(db_path, keep=2)
    dest3 = db.backup(db_path, keep=2)
    remaining = sorted(p.name for p in (db_path.parent / "backups").glob("*.sqlite3"))
    assert len(remaining) == 2 and dest1.name not in remaining and dest3.name in remaining
    # バックアップは開けて中身がある
    c = sqlite3.connect(dest3)
    assert c.execute("SELECT COUNT(*) FROM workspace").fetchone()[0] == 3
    c.close()
    assert dest2.exists()


def test_maybe_daily_backup_runs_once(db_path: Path, conn: sqlite3.Connection):
    first = db.maybe_daily_backup(db_path)
    assert first is not None
    assert db.maybe_daily_backup(db_path) is None  # 24 時間以内は再実行しない
