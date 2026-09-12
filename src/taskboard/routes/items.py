"""項目: クイック追加・移動・完了・ノート・詳細・編集。

htmx からの POST は HX-Target（差し替え先の id）を見て部分テンプレートを返し、
通常のフォーム POST は 303 で元の画面へ戻る（JS が無くても動く）。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import models as m
from .. import service
from ..deps import Conn, hx_target, is_htmx, render
from .workspaces import AUTHOR, SOURCE, board_context

router = APIRouter()


def _detail_context(conn: sqlite3.Connection, item: m.Item) -> dict:
    ws = service.get_workspace_by_id(conn, item.workspace_id)
    return {
        "ws": ws,
        "item": item,
        "notes": service.list_notes(conn, item.id),
        "events": service.list_events(conn, item_id=item.id, limit=200),
    }


def _after_write(request: Request, conn: sqlite3.Connection, item: m.Item, form: dict):
    """書き込み後の応答: htmx なら差し替え先に合わせた部分、それ以外は 303。"""
    target = hx_target(request) if is_htmx(request) else ""
    ws = service.get_workspace_by_id(conn, item.workspace_id)
    if target == "board":
        ctx = board_context(
            conn,
            ws,
            view=form.get("view") or "kanban",
            status=form.get("status_filter"),
            tag=form.get("tag"),
            owner=form.get("owner"),
            q=form.get("q"),
            sort=form.get("sort") or "updated",
            page=int(form.get("page") or 1),
        )
        return render(request, "_board.html", ctx)
    if target == "detail":
        return render(request, "_detail.html", _detail_context(conn, item))
    back = form.get("back") or f"/w/{ws.slug}"
    if not back.startswith("/"):
        back = f"/w/{ws.slug}"
    return RedirectResponse(back, status_code=303)


async def _form(request: Request) -> dict:
    data = await request.form()
    return {k: (v if isinstance(v, str) else "") for k, v in data.items()}


@router.post("/w/{slug}/items")
async def quick_add(request: Request, slug: str, conn: sqlite3.Connection = Conn, title: str = Form(...)):
    ws = service.get_workspace(conn, slug)
    form = await _form(request)
    item = service.add_item(conn, ws.id, title, author=AUTHOR, source=SOURCE)
    return _after_write(request, conn, item, form)


@router.post("/items/{item_id}/move")
async def move(request: Request, item_id: int, conn: sqlite3.Connection = Conn, status: str = Form(...), reason: str = Form("")):
    form = await _form(request)
    item = service.move_item(conn, item_id, status, reason=reason, author=AUTHOR, source=SOURCE)
    return _after_write(request, conn, item, form)


@router.post("/items/{item_id}/complete")
async def complete(request: Request, item_id: int, conn: sqlite3.Connection = Conn, summary: str = Form("")):
    form = await _form(request)
    item = service.complete_item(conn, item_id, summary=summary, author=AUTHOR, source=SOURCE)
    return _after_write(request, conn, item, form)


@router.post("/items/{item_id}/notes")
async def add_note(request: Request, item_id: int, conn: sqlite3.Connection = Conn, body: str = Form(...)):
    form = await _form(request)
    service.add_note(conn, item_id, body, author=AUTHOR, source=SOURCE)
    item = service.get_item(conn, item_id)
    return _after_write(request, conn, item, form)


def _item_in_workspace(conn: sqlite3.Connection, slug: str, item_id: int) -> m.Item:
    """URL の slug と項目の所属が一致しなければ 404（SPEC §2-1）。"""
    item = service.get_item(conn, item_id)
    if item.workspace != slug:
        raise m.NotFound(f"item #{item_id} is not in workspace '{slug}'")
    return item


@router.get("/w/{slug}/items/{item_id}")
def detail(request: Request, slug: str, item_id: int, conn: sqlite3.Connection = Conn):
    item = _item_in_workspace(conn, slug, item_id)
    ctx = _detail_context(conn, item)
    if is_htmx(request) and hx_target(request) == "detail":
        return render(request, "_detail.html", ctx)
    return render(request, "item.html", ctx)


@router.get("/w/{slug}/items/{item_id}/edit")
def edit_form(request: Request, slug: str, item_id: int, conn: sqlite3.Connection = Conn):
    item = _item_in_workspace(conn, slug, item_id)
    ctx = {"ws": service.get_workspace(conn, slug), "item": item, "error": None, "values": _edit_values(item)}
    if is_htmx(request) and hx_target(request) == "detail":
        return render(request, "_edit.html", ctx)
    return render(request, "edit.html", ctx)


def _edit_values(item: m.Item) -> dict:
    return {
        "title": item.title,
        "body": item.body,
        "priority": item.priority,
        "owner": item.owner or "",
        "due": item.due or "",
        "tags": " ".join(item.tags),
        "links": "\n".join(f"{l['kind']} {l['target']} {l['label']}".rstrip() for l in item.links),
    }


@router.post("/w/{slug}/items/{item_id}/edit")
async def edit_save(
    request: Request,
    slug: str,
    item_id: int,
    conn: sqlite3.Connection = Conn,
    title: str = Form(...),
    body: str = Form(""),
    priority: str = Form("normal"),
    owner: str = Form(""),
    due: str = Form(""),
    tags: str = Form(""),
    links: str = Form(""),
):
    item = _item_in_workspace(conn, slug, item_id)
    values = {"title": title, "body": body, "priority": priority, "owner": owner, "due": due, "tags": tags, "links": links}
    try:
        item = service.update_item(
            conn,
            item_id,
            title=title,
            body=body,
            priority=priority,
            owner=owner or None,
            due=due or None,
            tags=m.parse_tags(tags),
            links=m.parse_links(links),
            author=AUTHOR,
            source=SOURCE,
        )
    except m.Conflict:
        pass  # 変更なし＝そのまま詳細へ
    except m.ValidationError as e:
        ctx = {"ws": service.get_workspace(conn, slug), "item": item, "error": str(e), "values": values}
        name = "_edit.html" if is_htmx(request) and hx_target(request) == "detail" else "edit.html"
        return render(request, name, ctx, status_code=200 if name == "_edit.html" else 400)
    if is_htmx(request) and hx_target(request) == "detail":
        return render(request, "_detail.html", _detail_context(conn, item))
    return RedirectResponse(f"/w/{slug}/items/{item_id}", status_code=303)
