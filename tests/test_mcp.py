"""MCP サーバー: in-memory Client(mcp) で 9 ツールの正常系＋hidden/read_only の拒否＋author 固定＋source='mcp'（SPEC §9 v0.3）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from taskboard import db, service
from taskboard.app import ensure_initial_workspaces
from taskboard import mcp_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mcp_env(tmp_path: Path, monkeypatch):
    path = tmp_path / "mcp.sqlite3"
    monkeypatch.setenv("TASKBOARD_DB", str(path))
    monkeypatch.setenv("TASKBOARD_AUTHOR", "ai:test-bot")
    monkeypatch.setenv("TASKBOARD_BASE_URL", "http://127.0.0.1:8765")
    conn = db.init_db(path)
    ensure_initial_workspaces(conn)
    service.create_workspace(conn, "ro", "読み取り専用", ai_policy="read_only", author="human", source="ui")
    ro = service.get_workspace(conn, "ro")
    service.add_item(conn, ro.id, "ro の項目", author="human", source="ui")
    work = service.get_workspace(conn, "work")
    service.add_item(conn, work.id, "仕事の項目（hidden）", author="human", source="ui")
    conn.close()
    return path


@pytest.fixture
async def client(mcp_env):
    async with Client(mcp_server.mcp, raise_exceptions=True) as c:
        yield c


def _err(result) -> str:
    assert result.is_error, "expected a tool error"
    return result.content[0].text


@pytest.mark.anyio
async def test_tools_listed_with_output_schema(client: Client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "list_workspaces", "get_workspace_summary", "list_items", "get_item",
        "add_item", "update_item", "move_item", "add_note", "complete_item",
    }
    for t in tools.values():
        assert t.output_schema and t.output_schema.get("type") == "object", t.name  # Pydantic モデルなので必ず付く
    assert "author" not in tools["add_item"].input_schema["properties"]  # author は引数で受け付けない
    assert "status" not in tools["update_item"].input_schema["properties"]


@pytest.mark.anyio
async def test_read_tools_hide_hidden_workspace(client: Client):
    r = await client.call_tool("list_workspaces", {})
    slugs = [w["slug"] for w in r.structured_content["workspaces"]]
    assert "blog" in slugs and "dev" in slugs and "ro" in slugs and "work" not in slugs
    assert "not found" in _err(await client.call_tool("get_workspace_summary", {"workspace": "work"}))
    assert "not found" in _err(await client.call_tool("list_items", {"workspace": "work"}))
    assert "not found" in _err(await client.call_tool("get_item", {"item_id": 2}))  # work の項目
    assert "not found" in _err(await client.call_tool("get_item", {"item_id": 9999}))


@pytest.mark.anyio
async def test_write_flow_records_author_and_source(client: Client, mcp_env: Path):
    r = await client.call_tool(
        "add_item",
        {"workspace": "blog", "title": "MCP から追加 ✓", "body": "本文", "priority": "high", "due": "2026-12-31",
         "tags": ["MCP", "test"], "links": [{"kind": "task", "target": "t-demo0003", "label": "x"}]},
    )
    assert not r.is_error
    item = r.structured_content
    assert item["created_by"] == "ai:test-bot" and item["status"] == "candidate" and item["tags"] == ["mcp", "test"]
    assert item["url"] == f"http://127.0.0.1:8765/w/blog/items/{item['id']}"
    iid = item["id"]

    r = await client.call_tool("move_item", {"item_id": iid, "status": "doing", "reason": "着手"})
    assert r.structured_content["status"] == "doing"
    r = await client.call_tool("update_item", {"item_id": iid, "owner": "human", "due": "", "tags": ["x"]})
    assert r.structured_content["owner"] == "human" and r.structured_content["due"] is None and r.structured_content["tags"] == ["x"]
    r = await client.call_tool("add_note", {"item_id": iid, "body": "ノート"})
    assert r.structured_content["author"] == "ai:test-bot"
    r = await client.call_tool("complete_item", {"item_id": iid, "summary": "完了メモ"})
    assert r.structured_content["status"] == "done" and r.structured_content["completed_at"]

    r = await client.call_tool("get_item", {"item_id": iid})
    d = r.structured_content
    assert [n["body"] for n in d["notes"]] == ["ノート", "完了メモ"]
    kinds = [e["kind"] for e in d["events"]]
    assert kinds == ["item.completed", "note.added", "note.added", "item.updated", "item.moved", "item.created"]
    assert all(e["source"] == "mcp" and e["author"] == "ai:test-bot" for e in d["events"])

    r = await client.call_tool("list_items", {"workspace": "blog", "status": "done", "limit": 1})
    assert r.structured_content["total"] == 1 and r.structured_content["next_offset"] is None
    assert "body" not in r.structured_content["items"][0]
    r = await client.call_tool("get_workspace_summary", {"workspace": "blog"})
    assert r.structured_content["counts"]["done"] == 1 and r.structured_content["url"] == "http://127.0.0.1:8765/w/blog"

    # DB 側でも author / source が固定されている
    conn = db.connect(mcp_env)
    rows = conn.execute("SELECT DISTINCT author, source FROM event WHERE item_id = ?", (iid,)).fetchall()
    conn.close()
    assert [tuple(r) for r in rows] == [("ai:test-bot", "mcp")]


@pytest.mark.anyio
async def test_author_cannot_be_overridden_by_argument(client: Client):
    r = await client.call_tool("add_item", {"workspace": "blog", "title": "なりすまし", "author": "human"})
    # 引数 author は受け付けない（スキーマに無い）。拒否されるか無視されるかは SDK 次第だが、
    # どちらでも created_by が 'human' になることは無い
    if not r.is_error:
        assert r.structured_content["created_by"] == "ai:test-bot"
    else:
        assert "author" in r.content[0].text.lower() or "unexpected" in r.content[0].text.lower()


@pytest.mark.anyio
async def test_read_only_rejects_writes_but_allows_reads(client: Client):
    r = await client.call_tool("list_items", {"workspace": "ro"})
    assert not r.is_error and r.structured_content["total"] == 1
    ro_item = r.structured_content["items"][0]["id"]
    assert "read-only" in _err(await client.call_tool("add_item", {"workspace": "ro", "title": "x"}))
    assert "read-only" in _err(await client.call_tool("move_item", {"item_id": ro_item, "status": "doing"}))
    assert "read-only" in _err(await client.call_tool("add_note", {"item_id": ro_item, "body": "x"}))
    assert "read-only" in _err(await client.call_tool("update_item", {"item_id": ro_item, "title": "y"}))
    assert "read-only" in _err(await client.call_tool("complete_item", {"item_id": ro_item}))
    assert (await client.call_tool("get_item", {"item_id": ro_item})).is_error is False


@pytest.mark.anyio
async def test_validation_and_conflict_become_tool_errors(client: Client):
    r = await client.call_tool("add_item", {"workspace": "blog", "title": "v"})
    iid = r.structured_content["id"]
    assert "already" in _err(await client.call_tool("move_item", {"item_id": iid, "status": "candidate"}))
    assert "due" in _err(await client.call_tool("update_item", {"item_id": iid, "due": "2026-13-40"}))
    assert "nothing to update" in _err(await client.call_tool("update_item", {"item_id": iid}))
    assert "owner" in _err(await client.call_tool("add_item", {"workspace": "blog", "title": "o", "owner": "someone"}))
    assert "not found" in _err(await client.call_tool("add_item", {"workspace": "nope", "title": "o"}))
    assert (await client.call_tool("list_items", {"workspace": "blog", "limit": 999})).is_error  # ge/le は SDK が弾く


@pytest.mark.anyio
async def test_missing_author_env_disables_writes(mcp_env, monkeypatch):
    monkeypatch.delenv("TASKBOARD_AUTHOR")
    async with Client(mcp_server.mcp, raise_exceptions=True) as c:
        assert (await c.call_tool("list_workspaces", {})).is_error is False  # 読みは可
        assert "TASKBOARD_AUTHOR" in _err(await c.call_tool("add_item", {"workspace": "blog", "title": "x"}))
    monkeypatch.setenv("TASKBOARD_AUTHOR", "human")
    async with Client(mcp_server.mcp, raise_exceptions=True) as c:
        assert "ai:<name>" in _err(await c.call_tool("add_item", {"workspace": "blog", "title": "x"}))
