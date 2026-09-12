"""MCP stdio スパイク

公式 MCP Python SDK v2 (パッケージ名 `mcp`, 2.2.0) の高レベル API `MCPServer`
(v1 では `FastMCP` と呼ばれていたもの) で、メモリ上のリストに対する
`add_item` / `list_items` の2ツール (+診断用 spike_env) だけを持つ stdio サーバー。

起動 (ホストが子プロセスとして起動する。単体で叩くと stdin 待ちで黙るのが正常):
    uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py
    uv run --with "mcp[cli]==2.2.0" mcp run C:/path/to/ai-taskboard/spike/mcp_spike.py

注意:
- stdio では stdout がプロトコルそのもの。print() は使わない (logging の既定ハンドラ = stderr)。
- 戻り値の型注釈がそのまま output_schema になる。素の `dict` だと構造化出力にならないので
  TypedDict で形を宣言する (公式 docs: Servers > Structured Output)。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import TypedDict

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

logging.basicConfig(level=logging.INFO)  # 既定ハンドラは stderr
log = logging.getLogger("mcp_spike")

mcp = MCPServer("ai-taskboard-spike")


class Item(TypedDict):
    id: int
    title: str
    author: str
    created_at: str


class EnvInfo(TypedDict):
    cwd: str
    python: str
    executable: str
    claude_project_dir: str | None
    stdin_encoding: str | None
    stdout_encoding: str | None
    pythonioencoding: str | None


# メモリ上の仮リスト。プロセスが終われば消える (スパイク用)。
_ITEMS: list[Item] = []
_NEXT_ID = 1


@mcp.tool()
def add_item(title: str, author: str = "ai:unknown") -> Item:
    """Add an item to the in-memory list.

    Args:
        title: 項目のタイトル (日本語可)。空文字は拒否。
        author: 誰が書いたか。`human` または `ai:<name>`。
    """
    global _NEXT_ID
    if not title.strip():
        raise ToolError("title must not be empty")
    if author != "human" and not author.startswith("ai:"):
        raise ToolError("author must be 'human' or 'ai:<name>'")
    item: Item = {
        "id": _NEXT_ID,
        "title": title.strip(),
        "author": author,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _NEXT_ID += 1
    _ITEMS.append(item)
    log.info("add_item id=%s title=%r", item["id"], item["title"])
    return item


@mcp.tool()
def list_items() -> list[Item]:
    """List all items currently held in memory (oldest first)."""
    return list(_ITEMS)


@mcp.tool()
def spike_env() -> EnvInfo:
    """Diagnostics: how the host launched this server (cwd, CLAUDE_PROJECT_DIR, encodings)."""
    return {
        "cwd": os.getcwd(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "claude_project_dir": os.environ.get("CLAUDE_PROJECT_DIR"),
        "stdin_encoding": getattr(sys.stdin, "encoding", None),
        "stdout_encoding": getattr(sys.stdout, "encoding", None),
        "pythonioencoding": os.environ.get("PYTHONIOENCODING"),
    }


if __name__ == "__main__":
    mcp.run()  # 引数なし = stdio
