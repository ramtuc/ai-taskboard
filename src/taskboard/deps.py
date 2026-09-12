"""ルートが共通で使う依存関係とヘルパ（app.py と routes/ の循環 import を避けるため分離）。"""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from . import db


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """リクエストごとに接続を開いて閉じる（WAL なので Web と MCP の 2 プロセスで同じファイルを開ける）。"""
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Depends(get_conn)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def hx_target(request: Request) -> str:
    return request.headers.get("HX-Target", "")


def render(request: Request, name: str, ctx: dict, status_code: int = 200):
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)

