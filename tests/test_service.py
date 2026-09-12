"""service 層: 追加／一覧／移動／完了／ノート／更新で event が残ること、検証エラー（SPEC §9 v0.1/v0.2）。"""

from __future__ import annotations

import sqlite3

import pytest

from taskboard import models as m
from taskboard import service


def _events(conn, item_id):
    return service.list_events(conn, item_id=item_id, limit=100)


def test_add_item_logs_created_event(conn: sqlite3.Connection, blog):
    item = service.add_item(conn, blog.id, "  最初の候補  ", tags=["IC-Lab", "ne555"], author="ai:demo-assistant", source="mcp")
    assert item.title == "最初の候補" and item.status == "candidate" and item.created_by == "ai:demo-assistant"
    assert item.tags == ["ic-lab", "ne555"] and item.created_by_ai
    ev = _events(conn, item.id)
    assert len(ev) == 1 and ev[0].kind == "item.created" and ev[0].author == "ai:demo-assistant" and ev[0].source == "mcp"
    assert ev[0].payload == {"title": "最初の候補", "status": "candidate"}
    assert item.to_dict("http://127.0.0.1:8765")["url"] == f"http://127.0.0.1:8765/w/blog/items/{item.id}"


def test_move_item_records_from_to_and_completed_at(conn, blog):
    item = service.add_item(conn, blog.id, "a", author="human", source="ui")
    moved = service.move_item(conn, item.id, "doing", reason="着手", author="human", source="ui")
    assert moved.status == "doing" and moved.completed_at is None
    ev = _events(conn, item.id)
    assert ev[0].kind == "item.moved" and ev[0].payload == {"from": "candidate", "to": "doing", "reason": "着手"}
    done = service.move_item(conn, item.id, "done", author="ai:x", source="rest")
    assert done.completed_at is not None
    back = service.move_item(conn, item.id, "hold", author="human", source="ui")
    assert back.completed_at is None
    assert len(_events(conn, item.id)) == 4
    with pytest.raises(m.Conflict):
        service.move_item(conn, item.id, "hold", author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.move_item(conn, item.id, "flying", author="human", source="ui")


def test_move_puts_item_on_top_of_column(conn, blog):
    a = service.add_item(conn, blog.id, "a", author="human", source="ui")
    b = service.add_item(conn, blog.id, "b", author="human", source="ui")
    items, _ = service.list_items(conn, blog.id, status="candidate", sort="column")
    assert [i.id for i in items] == [b.id, a.id]  # 新しいものが先頭
    service.move_item(conn, a.id, "doing", author="human", source="ui")
    service.move_item(conn, b.id, "doing", author="human", source="ui")
    items, _ = service.list_items(conn, blog.id, status="doing", sort="column")
    assert [i.id for i in items] == [b.id, a.id]


def test_complete_item_adds_note_and_event(conn, blog):
    item = service.add_item(conn, blog.id, "c", author="human", source="ui")
    done = service.complete_item(conn, item.id, summary="終わった", author="ai:demo-assistant", source="mcp")
    assert done.status == "done" and done.completed_at
    notes = service.list_notes(conn, item.id)
    assert len(notes) == 1 and notes[0].body == "終わった" and notes[0].by_ai
    kinds = [e.kind for e in _events(conn, item.id)]
    assert kinds == ["item.completed", "note.added", "item.created"]
    with pytest.raises(m.Conflict):
        service.complete_item(conn, item.id, author="human", source="ui")


def test_add_note_validation_and_event(conn, blog):
    item = service.add_item(conn, blog.id, "n", author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.add_note(conn, item.id, "   ", author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.add_note(conn, item.id, "x" * 4001, author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.add_note(conn, item.id, "ok", author="robot", source="ui")
    note = service.add_note(conn, item.id, "ok", author="human", source="ui")
    ev = _events(conn, item.id)[0]
    assert ev.kind == "note.added" and ev.payload == {"note_id": note.id}
    with pytest.raises(m.NotFound):
        service.add_note(conn, 9999, "x", author="human", source="ui")


def test_update_item_fields_only_in_payload(conn, blog):
    item = service.add_item(conn, blog.id, "u", body="old", author="human", source="ui")
    with pytest.raises(m.Conflict):  # 変更なし
        service.update_item(conn, item.id, title="u", author="human", source="ui")
    upd = service.update_item(
        conn,
        item.id,
        body="secret body",
        priority="urgent",
        owner="ai:demo-assistant",
        due="2026-12-31",
        tags=["x"],
        links=[{"kind": "task", "target": "t-demo0001", "label": "l"}],
        author="human",
        source="ui",
    )
    assert upd.priority == "urgent" and upd.owner == "ai:demo-assistant" and upd.due == "2026-12-31"
    assert upd.tags == ["x"] and upd.links == [{"kind": "task", "target": "t-demo0001", "label": "l"}]
    ev = _events(conn, item.id)[0]
    assert ev.kind == "item.updated"
    assert set(ev.payload["fields"]) == {"body", "priority", "owner", "due", "tags", "links"}
    assert "secret" not in str(ev.payload)  # 本文は payload に入れない（SPEC §6-2）
    with pytest.raises(m.ValidationError):
        service.update_item(conn, item.id, due="2026-13-01", author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.update_item(conn, item.id, owner="someone", author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.update_item(conn, item.id, title="x" * 201, author="human", source="ui")


def test_list_items_filters(conn, blog):
    a = service.add_item(conn, blog.id, "555 timer", body="oscillator", tags=["ic-lab"], owner="human", author="human", source="ui")
    b = service.add_item(conn, blog.id, "esp32", tags=["esp32"], author="ai:demo-assistant", source="mcp")
    items, total = service.list_items(conn, blog.id, tag="ic-lab")
    assert total == 1 and items[0].id == a.id
    items, total = service.list_items(conn, blog.id, query="oscill")
    assert total == 1 and items[0].id == a.id
    items, total = service.list_items(conn, blog.id, owner="none")
    assert total == 1 and items[0].id == b.id
    _, total = service.list_items(conn, blog.id, limit=1)
    assert total == 2


def test_board_columns_done_truncated(conn, blog):
    for i in range(service.DONE_COLUMN_LIMIT + 3):
        service.add_item(conn, blog.id, f"d{i}", status="done", author="human", source="ui")
    cols = service.board_columns(conn, blog.id)
    assert cols["done"]["total"] == service.DONE_COLUMN_LIMIT + 3
    assert len(cols["done"]["items"]) == service.DONE_COLUMN_LIMIT and cols["done"]["truncated"]


def test_workspace_create_update_and_policy(conn):
    ws = service.create_workspace(conn, "lab", "実験室", ai_policy="read_only", author="human", source="ui")
    assert ws.ai_policy == "read_only"
    with pytest.raises(m.Conflict):
        service.create_workspace(conn, "lab", "dup", author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.create_workspace(conn, "Bad Slug", "x", author="human", source="ui")
    upd = service.update_workspace(conn, "lab", ai_policy="hidden", archived=True, author="human", source="ui")
    assert upd.ai_policy == "hidden" and upd.archived_at
    ev = service.list_events(conn, workspace_id=ws.id)[0]
    assert ev.kind == "workspace.updated" and ev.payload["ai_policy"] == {"from": "read_only", "to": "hidden"}
    # for_ai=True では hidden は存在しない扱い（v0.3 の MCP／REST が使う）
    assert "lab" not in [w.slug for w in service.list_workspaces(conn, include_archived=True, for_ai=True)]
    assert "work" not in [w.slug for w in service.list_workspaces(conn, for_ai=True)]
    with pytest.raises(m.NotFound):
        service.get_workspace(conn, "work", for_ai=True)
    work = service.get_workspace(conn, "work")  # UI からは見える
    with pytest.raises(m.NotFound):
        service.check_ai_writable(work)
    ro = service.create_workspace(conn, "ro", "読み取り専用", ai_policy="read_only", author="human", source="ui")
    with pytest.raises(m.ValidationError):
        service.check_ai_writable(ro)
    service.check_ai_writable(service.get_workspace(conn, "blog"))  # read_write は通る


def test_workspace_summary(conn, blog):
    late = service.add_item(conn, blog.id, "late", due="2020-01-01", author="human", source="ui")
    service.add_item(conn, blog.id, "ai turn", status="waiting_ai", author="human", source="ui")
    s = service.workspace_summary(conn, blog, "http://x")
    assert s["counts"]["candidate"] == 1 and s["counts"]["waiting_ai"] == 1
    assert [i["id"] for i in s["overdue"]] == [late.id]
    assert s["waiting_ai"][0]["title"] == "ai turn" and "body" not in s["waiting_ai"][0]
    assert s["url"] == "http://x/w/blog" and len(s["recent_events"]) == 3  # created ×2 + workspace.created
