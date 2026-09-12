"""FastAPI + SQLite + HTMX スパイク

SQLite の1テーブル (items) に対して「一覧 + 追加フォーム」だけの最小ページ。
追加は HTMX の hx-post で一覧部分だけを差し替える (フルリロードなし・ビルド工程なし)。

起動:  uv run --directory C:/path/to/ai-taskboard/spike web_spike.py
       (環境変数 SPIKE_PORT で固定可。未指定なら 8000〜8099 の空きを使う)
バインドは 127.0.0.1 のみ (localhost 以外からは到達できない)。
"""

from __future__ import annotations

import os
import socket
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "spike.db"
HOST = "127.0.0.1"


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with closing(db()) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                author     TEXT    NOT NULL DEFAULT 'human',
                created_at TEXT    NOT NULL
            )
            """
        )
        con.commit()


def fetch_items() -> list[sqlite3.Row]:
    with closing(db()) as con:
        return con.execute("SELECT id, title, author, created_at FROM items ORDER BY id").fetchall()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ai-taskboard spike", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")  # autoescape は Jinja2Templates の既定で有効


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"items": fetch_items()})


@app.post("/items", response_class=HTMLResponse)
def create_item(request: Request, title: str = Form(...), author: str = Form("human")):
    title = title.strip()
    if title:
        with closing(db()) as con:
            con.execute(
                "INSERT INTO items (title, author, created_at) VALUES (?, ?, ?)",
                (title, author, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            con.commit()
    # 部分テンプレートだけを返し、HTMX が #item-list を差し替える
    return templates.TemplateResponse(request, "_items.html", {"items": fetch_items()})


@app.get("/api/items")
def api_items():
    # REST 側の口も同じ関数を使う、という将来形の最小デモ
    return [dict(r) for r in fetch_items()]


def pick_port() -> int:
    if os.environ.get("SPIKE_PORT"):
        return int(os.environ["SPIKE_PORT"])
    for port in range(8000, 8100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    raise RuntimeError("no free port in 8000-8099")


if __name__ == "__main__":
    port = pick_port()
    print(f"spike: http://{HOST}:{port}/  (pid={os.getpid()})", flush=True)
    uvicorn.run(app, host=HOST, port=port, log_level="info")
