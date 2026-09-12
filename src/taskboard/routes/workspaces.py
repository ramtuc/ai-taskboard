"""ワークスペース一覧・作成・設定・ボード（かんばん／リスト）。"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import models as m
from .. import service
from ..deps import Conn, hx_target, is_htmx, render

router = APIRouter()
AUTHOR = "human"
SOURCE = "ui"
PAGE_SIZE = 50


@router.get("/")
def index(request: Request, conn: sqlite3.Connection = Conn):
    cards = []
    for ws in service.list_workspaces(conn, include_archived=False):
        cards.append(
            {
                "ws": ws,
                "counts": service.workspace_counts(conn, ws.id),
                "last": service.workspace_last_activity(conn, ws.id),
            }
        )
    archived = service.list_workspaces(conn, include_archived=True)
    archived = [w for w in archived if w.archived_at]
    return render(request, "index.html", {"cards": cards, "archived": archived})


@router.get("/workspaces/new")
def workspace_new_form(request: Request):
    return render(request, "workspace_new.html", {"values": {"ai_policy": "read_write"}, "error": None})


@router.post("/workspaces/new")
def workspace_new(
    request: Request,
    conn: sqlite3.Connection = Conn,
    name: str = Form(...),
    slug: str = Form(""),
    description: str = Form(""),
    ai_policy: str = Form("read_write"),
):
    slug = (slug or "").strip() or m.slugify(name)
    try:
        ws = service.create_workspace(
            conn, slug, name, description=description, ai_policy=ai_policy, author=AUTHOR, source=SOURCE
        )
    except (m.ValidationError, m.Conflict) as e:
        values = {"name": name, "slug": slug, "description": description, "ai_policy": ai_policy}
        return render(request, "workspace_new.html", {"values": values, "error": str(e)}, status_code=400)
    return RedirectResponse(f"/w/{ws.slug}", status_code=303)


def board_context(
    conn: sqlite3.Connection,
    ws: m.Workspace,
    *,
    view: str = "kanban",
    status: str | None = None,
    tag: str | None = None,
    owner: str | None = None,
    q: str | None = None,
    sort: str = "updated",
    page: int = 1,
) -> dict:
    view = "list" if view == "list" else "kanban"
    tag = (tag or "").strip() or None
    owner = (owner or "").strip() or None
    q = (q or "").strip() or None
    status = (status or "").strip() or None
    if status and status not in m.STATUSES:
        status = None
    ctx = {
        "ws": ws,
        "view": view,
        "filters": {"status": status, "tag": tag, "owner": owner, "q": q, "sort": sort},
        "tags": service.all_tags(conn, ws.id),
        "owners": service.all_owners(conn, ws.id),
        "counts": service.workspace_counts(conn, ws.id),
    }
    if view == "kanban":
        ctx["columns"] = service.board_columns(conn, ws.id, tag=tag, owner=owner, query=q)
    else:
        page = max(1, int(page or 1))
        items, total = service.list_items(
            conn, ws.id, status=status, tag=tag, owner=owner, query=q, sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
        )
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        ctx.update({"items": items, "total": total, "page": page, "pages": pages})
    return ctx


@router.get("/w/{slug}")
def board(
    request: Request,
    slug: str,
    conn: sqlite3.Connection = Conn,
    view: str = "kanban",
    status: str | None = None,
    tag: str | None = None,
    owner: str | None = None,
    q: str | None = None,
    sort: str = "updated",
    page: int = 1,
):
    ws = service.get_workspace(conn, slug)
    ctx = board_context(conn, ws, view=view, status=status, tag=tag, owner=owner, q=q, sort=sort, page=page)
    if is_htmx(request) and hx_target(request) == "board":
        return render(request, "_board.html", ctx)
    return render(request, "board.html", ctx)


@router.get("/w/{slug}/settings")
def settings_form(request: Request, slug: str, conn: sqlite3.Connection = Conn):
    ws = service.get_workspace(conn, slug)
    return render(request, "settings.html", {"ws": ws, "error": None, "saved": False})


@router.post("/w/{slug}/settings")
def settings_save(
    request: Request,
    slug: str,
    conn: sqlite3.Connection = Conn,
    name: str = Form(...),
    description: str = Form(""),
    ai_policy: str = Form("read_write"),
    archived: str = Form(""),
):
    ws = service.get_workspace(conn, slug)
    try:
        ws = service.update_workspace(
            conn,
            slug,
            name=name,
            description=description,
            ai_policy=ai_policy,
            archived=(archived == "1"),
            author=AUTHOR,
            source=SOURCE,
        )
    except m.ValidationError as e:
        return render(request, "settings.html", {"ws": ws, "error": str(e), "saved": False}, status_code=400)
    return render(request, "settings.html", {"ws": ws, "error": None, "saved": True})
