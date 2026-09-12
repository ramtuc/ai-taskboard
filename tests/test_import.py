"""取り込み（SPEC §7）: JSON／CSV・重複スキップ・dry-run・デモ seed。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from taskboard import db, service
from taskboard.cli import main as cli_main
from taskboard.cli import seed_dir
from taskboard.importer import import_file
from taskboard.models import ValidationError

DOC = {
    "format": "taskboard-import",
    "version": 1,
    "workspaces": [{"slug": "blog", "name": "ブログ", "ai_policy": "read_write"}, {"slug": "lab", "name": "実験室", "ai_policy": "hidden"}],
    "items": [
        {
            "workspace": "blog",
            "title": "取り込みテスト",
            "body": "- a\n- b",
            "status": "waiting_human",
            "priority": "high",
            "owner": "human",
            "tags": ["pc-setup", "owon"],
            "links": [{"kind": "task", "target": "t-demo0002", "label": "ドラフト"}],
            "created_by": "ai:demo-assistant",
            "notes": [{"author": "ai:demo-assistant", "body": "ノート 1"}],
        },
        {"workspace": "lab", "title": "hidden の項目"},
        {"workspace": "newws", "title": "無いワークスペースは作られる"},
    ],
}


def test_import_json_then_duplicate_skip(conn: sqlite3.Connection, tmp_path: Path):
    p = tmp_path / "in.json"
    p.write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
    rep = import_file(conn, p)
    assert rep.items_created == 3 and rep.workspaces_created == ["lab", "newws"] and rep.notes_created == 1
    item = service.list_items(conn, service.get_workspace(conn, "blog").id, query="取り込み")[0][0]
    assert item.status == "waiting_human" and item.tags == ["owon", "pc-setup"] and item.created_by == "ai:demo-assistant"
    ev = service.list_events(conn, item_id=item.id)
    assert ev[-1].kind == "item.created" and ev[-1].source == "import" and ev[-1].payload["import_file"] == "in.json"
    assert service.get_workspace(conn, "lab").ai_policy == "hidden"
    # 2 回目は全部スキップ（上書きしない）
    rep2 = import_file(conn, p)
    assert rep2.items_created == 0 and len(rep2.items_skipped) == 3 and rep2.notes_created == 0


def test_import_dry_run_writes_nothing(conn: sqlite3.Connection, tmp_path: Path):
    p = tmp_path / "in.json"
    p.write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
    rep = import_file(conn, p, dry_run=True)
    assert rep.dry_run and rep.items_created == 3
    assert conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM workspace").fetchone()[0] == 3


def test_import_csv(conn: sqlite3.Connection, tmp_path: Path):
    p = tmp_path / "in.csv"
    p.write_text(
        "workspace,title,status,priority,owner,due,tags,body\n"
        'blog,CSV の項目,doing,high,human,2026-10-01,esp32;sensor,"1 行目\\n2 行目"\n'
        "dev,二つ目,,,,,,\n",
        encoding="utf-8",
    )
    rep = import_file(conn, p, default_author="human")
    assert rep.items_created == 2 and not rep.errors
    item = service.list_items(conn, service.get_workspace(conn, "blog").id, query="CSV")[0][0]
    assert item.status == "doing" and item.tags == ["esp32", "sensor"] and item.body == "1 行目\n2 行目" and item.due == "2026-10-01"
    two = service.list_items(conn, service.get_workspace(conn, "dev").id)[0][0]
    assert two.status == "candidate" and two.priority == "normal" and two.owner is None
    bad = tmp_path / "bad.csv"
    bad.write_text("title,workspace\nx,blog\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        import_file(conn, bad)


def test_import_rejects_wrong_format(conn: sqlite3.Connection, tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text('{"format": "other"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        import_file(conn, p)


def test_demo_seed_is_fictional_and_complete(tmp_path: Path):
    demo = seed_dir() / "demo.json"
    doc = json.loads(demo.read_text(encoding="utf-8"))
    slugs = {w["slug"] for w in doc["workspaces"]}
    assert slugs == {"blog", "workshop", "reading"} and "work" not in slugs  # 実運用の「仕事」は作らない
    authors = {i.get("created_by") for i in doc["items"]} | {n["author"] for i in doc["items"] for n in i.get("notes", [])}
    assert authors <= {"human", "ai:demo-assistant"}  # 実運用の author 名を出さない
    assert len(doc["items"]) == 18
    target = tmp_path / "demo.sqlite3"
    rc = cli_main(["seed", "--demo", "--db", str(target)])
    assert rc == 0
    conn = db.connect(target)
    try:
        statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM item")}
        assert statuses == {"candidate", "doing", "waiting_human", "waiting_ai", "done", "hold"}
        assert conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 18
        assert conn.execute("SELECT COUNT(*) FROM event WHERE kind='item.moved' AND author='ai:demo-assistant'").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM item WHERE created_by='ai:demo-assistant'").fetchone()[0] == 5
    finally:
        conn.close()


def test_cli_init_db_and_backup(tmp_path: Path, capsys):
    target = tmp_path / "d" / "t.sqlite3"
    assert cli_main(["init-db", "--db", str(target)]) == 0
    assert "['blog', 'work', 'dev']" in capsys.readouterr().out
    assert cli_main(["backup", "--db", str(target)]) == 0
    assert list((tmp_path / "d" / "backups").glob("t-*.sqlite3"))
    assert cli_main(["backup", "--db", str(tmp_path / "none.sqlite3")]) == 2
