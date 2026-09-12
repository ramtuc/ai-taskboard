"""統合: Web（uvicorn 子プロセス）と MCP（stdio 子プロセス）が同じ SQLite を開き、MCP の書き込みが Web に即反映される（WAL）。

自分が起動した子プロセスだけを終了する。ポートは 8100〜8199 の空きを使う。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters


def _free_port() -> int:
    for port in range(8100, 8200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port")


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 — localhost のみ
        return r.read().decode("utf-8")


@pytest.fixture
def web(tmp_path: Path):
    db_path = tmp_path / "shared.sqlite3"
    port = _free_port()
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("TASKBOARD_DB", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "taskboard.cli", "serve", "--db", str(db_path), "--port", str(port), "--no-backup"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                if '"ok":true' in _get(f"http://127.0.0.1:{port}/healthz"):
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("web server did not start")
        yield db_path, f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()  # 自分の PID だけ
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_mcp_subprocess_writes_are_visible_in_web(web):
    db_path, base = web
    assert "ブログ" in _get(f"{base}/")  # 初期ワークスペースは Web 側の起動で作られた

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "taskboard.cli", "mcp"],
        env={**os.environ, "TASKBOARD_DB": str(db_path), "TASKBOARD_AUTHOR": "ai:integration-bot", "TASKBOARD_BASE_URL": base, "PYTHONUTF8": "1"},
    )

    async def run():
        async with Client(params) as client:
            r = await client.call_tool("add_item", {"workspace": "blog", "title": "2 プロセス統合 ✓", "tags": ["wal"]})
            assert not r.is_error, r.content
            item = r.structured_content
            # Web を経由せず、その場で Web の画面に出る
            html = _get(item["url"])
            assert "2 プロセス統合 ✓" in html and "badge-ai" in html and "integration-bot" in html
            board = _get(f"{base}/w/blog")
            assert "2 プロセス統合 ✓" in board
            # 逆方向: Web（UI・human）でノートを書くと MCP から読める
            data = "body=Web+%E3%81%8B%E3%82%89%E3%81%AE%E3%83%8E%E3%83%BC%E3%83%88"  # 'Web からのノート'
            req = urllib.request.Request(f"{base}/items/{item['id']}/notes", data=data.encode(), method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded", "HX-Request": "true", "HX-Target": "detail"})
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                assert resp.status == 200
            d = (await client.call_tool("get_item", {"item_id": item["id"]})).structured_content
            assert [n["author"] for n in d["notes"]] == ["human"] and d["notes"][0]["body"] == "Web からのノート"
            assert "work" not in [w["slug"] for w in (await client.call_tool("list_workspaces", {})).structured_content["workspaces"]]

    anyio.run(run)
