"""REST API `/api/v1`（SPEC §4-4 / §6-1）— 他の AI やスクリプトから叩く口。MCP と同じ service 関数を呼ぶ。

認証: `Authorization: Bearer <TASKBOARD_API_TOKEN>` 必須。環境変数が未設定なら REST 全体を無効化（404）。
作成者: `X-Taskboard-Author: ai:<name>` 必須（形式違いは 400）。source='rest'。
ai_policy: MCP と同じ（hidden＝404・read_only の書き込み＝403）。UI（/w/...）だけが hidden を見られる。
エラーは FastAPI 標準の {"detail": "..."}（404 不明／400 検証／403 ai_policy／409 競合／401 認証）。
"""

from __future__ import annotations

import os
import secrets
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from . import models as m
from . import service
from .deps import Conn
from .schemas import (
    CompleteIn,
    EventSummary,
    Item,
    ItemCreate,
    ItemDetail,
    ItemList,
    ItemSummary,
    ItemUpdate,
    MoveIn,
    Note,
    NoteIn,
    WorkspaceList,
    WorkspaceSummary,
    base_url,
    workspace_info,
)

SOURCE = "rest"
TOKEN_ENV = "TASKBOARD_API_TOKEN"


def api_token() -> str | None:
    return os.environ.get(TOKEN_ENV) or None


def require_bearer(request: Request, authorization: str | None = Header(default=None)) -> None:
    token = api_token()
    if not token:
        # REST は明示的にトークンを置いたときだけ有効（未設定＝存在しない扱い）
        raise HTTPException(status_code=404, detail="REST API is disabled: set TASKBOARD_API_TOKEN to enable")
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value or not secrets.compare_digest(value.strip(), token):
        raise HTTPException(status_code=401, detail="missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})


def require_author(x_taskboard_author: str | None = Header(default=None)) -> str:
    if not x_taskboard_author:
        raise HTTPException(status_code=400, detail="X-Taskboard-Author header is required (e.g. ai:gemini-analytics)")
    try:
        return m.validate_author(x_taskboard_author.strip())
    except m.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


router = APIRouter(prefix="/api/v1", tags=["api"], dependencies=[Depends(require_bearer)])
Author = Depends(require_author)


@router.get("/workspaces", response_model=WorkspaceList)
def list_workspaces(conn: sqlite3.Connection = Conn, author: str = Author):
    return WorkspaceList(
        workspaces=[workspace_info(conn, ws, service.workspace_counts(conn, ws.id)) for ws in service.list_workspaces(conn, for_ai=True)]
    )


@router.get("/workspaces/{slug}/summary", response_model=WorkspaceSummary)
def workspace_summary(slug: str, conn: sqlite3.Connection = Conn, author: str = Author):
    ws = service.ai_get_workspace(conn, slug)
    return WorkspaceSummary(**service.workspace_summary(conn, ws, base_url()))


@router.get("/workspaces/{slug}/items", response_model=ItemList)
def list_items(
    slug: str,
    conn: sqlite3.Connection = Conn,
    author: str = Author,
    status: str | None = None,
    tag: str | None = None,
    owner: str | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    ws = service.ai_get_workspace(conn, slug)
    items, total = service.list_items(conn, ws.id, status=status, tag=tag, owner=owner, query=q, sort="updated", limit=limit, offset=offset)
    next_offset = offset + len(items) if offset + len(items) < total else None
    return ItemList(items=[ItemSummary.from_model(i) for i in items], total=total, next_offset=next_offset)


@router.post("/workspaces/{slug}/items", response_model=Item, status_code=201)
def add_item(slug: str, body: ItemCreate, conn: sqlite3.Connection = Conn, author: str = Author):
    ws = service.ai_get_workspace(conn, slug, write=True)
    item = service.add_item(
        conn,
        ws.id,
        body.title,
        body=body.body,
        priority=body.priority,
        owner=body.owner,
        due=body.due,
        tags=body.tags,
        links=[l.model_dump() for l in body.links],
        author=author,
        source=SOURCE,
    )
    return Item.from_model(item)


@router.get("/items/{item_id}", response_model=ItemDetail)
def get_item(item_id: int, conn: sqlite3.Connection = Conn, author: str = Author):
    item = service.ai_get_item(conn, item_id)
    return ItemDetail(
        item=Item.from_model(item),
        notes=[Note.from_model(n) for n in service.list_notes(conn, item.id)],
        events=[EventSummary.from_model(e) for e in service.list_events(conn, item_id=item.id, limit=100)],
    )


@router.patch("/items/{item_id}", response_model=Item)
async def update_item(item_id: int, request: Request, conn: sqlite3.Connection = Conn, author: str = Author):
    raw = await request.json()
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    if "status" in raw:
        raise HTTPException(status_code=400, detail="status cannot be changed here: use POST /items/{id}/move")
    try:
        body = ItemUpdate.model_validate(raw)
    except Exception as e:  # pydantic.ValidationError
        raise HTTPException(status_code=400, detail=str(e)) from e
    service.ai_get_item(conn, item_id, write=True)
    kwargs: dict = {}
    for name in ("title", "body", "priority", "tags"):
        value = getattr(body, name)
        if value is not None:
            kwargs[name] = value
    if body.owner is not None:
        kwargs["owner"] = body.owner or None
    if body.due is not None:
        kwargs["due"] = body.due or None
    if body.links is not None:
        kwargs["links"] = [l.model_dump() for l in body.links]
    if not kwargs:
        raise HTTPException(status_code=400, detail="nothing to update")
    return Item.from_model(service.update_item(conn, item_id, author=author, source=SOURCE, **kwargs))


@router.post("/items/{item_id}/move", response_model=Item)
def move_item(item_id: int, body: MoveIn, conn: sqlite3.Connection = Conn, author: str = Author):
    service.ai_get_item(conn, item_id, write=True)
    return Item.from_model(service.move_item(conn, item_id, body.status, reason=body.reason, author=author, source=SOURCE))


@router.post("/items/{item_id}/notes", response_model=Note, status_code=201)
def add_note(item_id: int, body: NoteIn, conn: sqlite3.Connection = Conn, author: str = Author):
    service.ai_get_item(conn, item_id, write=True)
    return Note.from_model(service.add_note(conn, item_id, body.body, author=author, source=SOURCE))


@router.post("/items/{item_id}/complete", response_model=Item)
def complete_item(item_id: int, body: CompleteIn, conn: sqlite3.Connection = Conn, author: str = Author):
    service.ai_get_item(conn, item_id, write=True)
    return Item.from_model(service.complete_item(conn, item_id, summary=body.summary, author=author, source=SOURCE))


@router.get("/events", response_model=list[EventSummary])
def events(
    conn: sqlite3.Connection = Conn,
    author: str = Author,
    workspace: str | None = None,
    since: str | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    """監査用（MCP には出さない）。hidden のワークスペースのイベントは返さない。"""
    if workspace:
        ws = service.ai_get_workspace(conn, workspace)
        evs = service.list_events(conn, workspace_id=ws.id, since=since, limit=limit)
    else:
        visible = {w.id for w in service.list_workspaces(conn, include_archived=True, for_ai=True)}
        evs = [e for e in service.list_events(conn, since=since, limit=limit) if e.workspace_id in visible]
    return [EventSummary.from_model(e) for e in evs]
