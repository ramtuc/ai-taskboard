"""mcp_spike の自動テスト。
1) インメモリ (Client(server)) と 2) 実 stdio 子プロセス (uv run) の両方で
add_item/list_items を呼び、日本語が壊れないことを確認する。
実行: uv run --directory C:/path/to/ai-taskboard/spike python -m pytest -q  (pytest 未導入なら python tests/test_mcp_spike.py)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # cp932 コンソール対策 (ハーネス側の都合)

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from mcp import Client, StdioServerParameters  # noqa: E402

JP = "日本語のタイトル ✓ 〜 ①"


async def _exercise(client: Client) -> dict:
    tools = await client.list_tools()
    names = sorted(t.name for t in tools.tools)
    r1 = await client.call_tool("add_item", {"title": JP, "author": "ai:test"})
    r2 = await client.call_tool("list_items", {})
    r3 = await client.call_tool("spike_env", {})
    return {
        "tools": names,
        "add": r1.structured_content,
        "list": r2.structured_content,
        "env": r3.structured_content,
        "add_text": [c.text for c in r1.content if getattr(c, "type", "") == "text"],
    }


async def run_inmemory() -> dict:
    import mcp_spike

    async with Client(mcp_spike.mcp) as client:
        return await _exercise(client)


async def run_stdio() -> dict:
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", str(HERE), "mcp_spike.py"],
        env={**os.environ},
    )
    async with Client(params) as client:
        return await _exercise(client)


def _check(res: dict, label: str) -> None:
    assert {"add_item", "list_items"} <= set(res["tools"]), res["tools"]
    assert res["add"]["title"] == JP, res["add"]
    items = res["list"]["result"]  # list[...] は {"result": [...]} に包まれる (公式 docs: Lists)
    assert any(i["title"] == JP for i in items), items
    print(f"[{label}] OK tools={res['tools']}")
    print(f"[{label}] env={json.dumps(res['env'], ensure_ascii=False)}")


def test_inmemory():
    _check(anyio.run(run_inmemory), "inmemory")


def test_stdio_subprocess():
    _check(anyio.run(run_stdio), "stdio")


if __name__ == "__main__":
    test_inmemory()
    test_stdio_subprocess()
    print("ALL OK")
