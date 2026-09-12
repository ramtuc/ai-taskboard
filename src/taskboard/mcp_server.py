"""MCP サーバー（stdio）— Claude Code などのホストが子プロセスとして起動する（SPEC §4-2 / §4-3）。

起動:  uv run --directory C:/path/to/ai-taskboard taskboard mcp
環境変数:
  TASKBOARD_AUTHOR  書き込みの author（`ai:<名前>`・必須）。ツール引数では受け付けない（なりすまし防止）
  TASKBOARD_DB      SQLite ファイル（既定 data/taskboard.sqlite3）
  TASKBOARD_BASE_URL 戻り値の url の土台（既定 http://127.0.0.1:8765）

約束（SPEC §4-2）:
- 戻り値は Pydantic モデル（SDK が output_schema / structured_content を作る）
- 失敗は ToolError（モデルに文言が届く）。service の NotFound / ValidationError / Conflict をそのまま読み替える
- hidden のワークスペースは存在しないものとして扱う。read_only は書き込み系で拒否
- stdout はプロトコル。print() しない（logging は stderr）
"""

from __future__ import annotations

import functools
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Callable, Iterator

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from . import db, models as m, service
from .schemas import (
    EventSummary,
    Item,
    ItemDetail,
    ItemList,
    ItemSummary,
    Link,
    Note,
    Priority,
    Status,
    WorkspaceInfo,
    WorkspaceList,
    WorkspaceSummary,
    base_url,
    workspace_info,
)

log = logging.getLogger("taskboard.mcp")
SOURCE = "mcp"

mcp = MCPServer(
    "taskboard",
    instructions=(
        "ai-taskboard: 人と AI が共有する候補・残項目ボード。ワークスペース(slug)ごとに項目を管理する。"
        "まず list_workspaces か get_workspace_summary で状況を見てから add_item / move_item / add_note を使う。"
        "状態は candidate/doing/waiting_human/waiting_ai/done/hold。書き込みの author はサーバー側で固定される。"
    ),
)

_migrated: set[str] = set()


def db_path() -> Path:
    return db.default_db_path()


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    """呼び出しごとに接続を開いて閉じる（初回だけマイグレーション）。Web サーバーが動いていなくても動く。"""
    path = db_path()
    key = str(path.resolve()) if path.exists() else str(path)
    if key not in _migrated:
        conn = db.init_db(path)
        from .app import ensure_initial_workspaces  # Web を一度も起動していなくても blog/work/dev を用意する

        ensure_initial_workspaces(conn)
        _migrated.add(key)
    else:
        conn = db.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def author() -> str:
    """書き込みの author。環境変数だけから決まり、ツール引数では変えられない。"""
    value = os.environ.get("TASKBOARD_AUTHOR", "").strip()
    if not value:
        raise ToolError("TASKBOARD_AUTHOR is not set on the server (expected 'ai:<name>'); writes are disabled")
    try:
        m.validate_author(value)
    except m.ValidationError as e:
        raise ToolError(f"TASKBOARD_AUTHOR is invalid: {e}") from e
    if not value.startswith("ai:"):
        raise ToolError("TASKBOARD_AUTHOR must be 'ai:<name>' for the MCP server")
    return value


def tool_errors(fn: Callable) -> Callable:
    """service の例外を ToolError に読み替える（モデルが読んで自己修正できるように）。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (m.NotFound, m.ValidationError, m.Conflict) as e:  # Forbidden は ValidationError の派生
            raise ToolError(str(e)) from e

    return wrapper


def _links(links: list[Link] | None) -> list[dict[str, str]]:
    return [l.model_dump() for l in links or []]


# ---------------------------------------------------------------------------
# 読み取り
# ---------------------------------------------------------------------------
@mcp.tool()
@tool_errors
def list_workspaces() -> WorkspaceList:
    """AI から見えるワークスペースの一覧（slug・名前・ai_policy・状態別件数）。hidden のものは含まれない。"""
    with session() as conn:
        out: list[WorkspaceInfo] = []
        for ws in service.list_workspaces(conn, for_ai=True):
            out.append(workspace_info(conn, ws, service.workspace_counts(conn, ws.id)))
        return WorkspaceList(workspaces=out)


@mcp.tool()
@tool_errors
def get_workspace_summary(
    workspace: Annotated[str, Field(description="ワークスペースの slug（例: blog）")],
) -> WorkspaceSummary:
    """ワークスペースの状況: 状態別件数・期限切れ・AI 待ち（waiting_ai）の項目・直近 20 件のイベント。セッション開始時にまず呼ぶ。"""
    with session() as conn:
        ws = service.ai_get_workspace(conn, workspace)
        return WorkspaceSummary(**service.workspace_summary(conn, ws, base_url()))


@mcp.tool()
@tool_errors
def list_items(
    workspace: Annotated[str, Field(description="ワークスペースの slug")],
    status: Annotated[Status | None, Field(description="状態で絞る（省略で全部）")] = None,
    tag: Annotated[str | None, Field(description="タグで絞る（英小文字）")] = None,
    owner: Annotated[str | None, Field(description="担当で絞る: 'human' / 'ai:<name>' / 'none'（未割当）")] = None,
    query: Annotated[str | None, Field(description="タイトル・本文の部分一致")] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="最大件数（1〜200）")] = 50,
    offset: Annotated[int, Field(ge=0, description="読み飛ばす件数（ページング）")] = 0,
) -> ItemList:
    """項目の一覧（本文なし）。更新が新しい順。続きがあれば next_offset が入る。"""
    with session() as conn:
        ws = service.ai_get_workspace(conn, workspace)
        items, total = service.list_items(
            conn, ws.id, status=status, tag=tag, owner=owner, query=query, sort="updated", limit=limit, offset=offset
        )
        next_offset = offset + len(items) if offset + len(items) < total else None
        return ItemList(items=[ItemSummary.from_model(i) for i in items], total=total, next_offset=next_offset)


@mcp.tool()
@tool_errors
def get_item(item_id: Annotated[int, Field(description="項目 ID（#番号）")]) -> ItemDetail:
    """項目 1 件の詳細（本文・ノート・履歴）。"""
    with session() as conn:
        item = service.ai_get_item(conn, item_id)
        return ItemDetail(
            item=Item.from_model(item),
            notes=[Note.from_model(n) for n in service.list_notes(conn, item.id)],
            events=[EventSummary.from_model(e) for e in service.list_events(conn, item_id=item.id, limit=100)],
        )


# ---------------------------------------------------------------------------
# 書き込み（author は環境変数で固定・source='mcp'・event が必ず残る）
# ---------------------------------------------------------------------------
@mcp.tool()
@tool_errors
def add_item(
    workspace: Annotated[str, Field(description="ワークスペースの slug")],
    title: Annotated[str, Field(min_length=1, max_length=200, description="タイトル（1〜200 文字）")],
    body: Annotated[str, Field(description="本文（Markdown・省略可）")] = "",
    priority: Annotated[Priority, Field(description="優先度")] = "normal",
    owner: Annotated[str | None, Field(description="次に動く人: 'human' か 'ai:<name>'（省略可）")] = None,
    due: Annotated[str | None, Field(description="期限 'YYYY-MM-DD'（省略可）")] = None,
    tags: Annotated[list[str], Field(description="タグ（英小文字・数字・._-）")] = [],
    links: Annotated[list[Link], Field(description="関連リンク（article/task/url）")] = [],
) -> Item:
    """候補として項目を追加する（状態は candidate）。作成者はサーバー側の設定で固定される。"""
    with session() as conn:
        ws = service.ai_get_workspace(conn, workspace, write=True)
        item = service.add_item(
            conn,
            ws.id,
            title,
            body=body,
            priority=priority,
            owner=owner,
            due=due,
            tags=tags,
            links=_links(links),
            author=author(),
            source=SOURCE,
        )
        return Item.from_model(item)


@mcp.tool()
@tool_errors
def update_item(
    item_id: Annotated[int, Field(description="項目 ID")],
    title: Annotated[str | None, Field(max_length=200)] = None,
    body: Annotated[str | None, Field(description="本文（Markdown）。全置換")] = None,
    priority: Priority | None = None,
    owner: Annotated[str | None, Field(description="'human' / 'ai:<name>'。'' で解除")] = None,
    due: Annotated[str | None, Field(description="'YYYY-MM-DD'。'' で解除")] = None,
    tags: Annotated[list[str] | None, Field(description="タグ（全置換）")] = None,
    links: Annotated[list[Link] | None, Field(description="リンク（全置換）")] = None,
) -> Item:
    """項目の属性を変更する（省略した引数は変えない）。状態（status）はここでは変えられない: move_item を使う。"""
    with session() as conn:
        service.ai_get_item(conn, item_id, write=True)
        kwargs: dict = {}
        if title is not None:
            kwargs["title"] = title
        if body is not None:
            kwargs["body"] = body
        if priority is not None:
            kwargs["priority"] = priority
        if owner is not None:
            kwargs["owner"] = owner or None
        if due is not None:
            kwargs["due"] = due or None
        if tags is not None:
            kwargs["tags"] = tags
        if links is not None:
            kwargs["links"] = _links(links)
        if not kwargs:
            raise ToolError("nothing to update: pass at least one field")
        item = service.update_item(conn, item_id, author=author(), source=SOURCE, **kwargs)
        return Item.from_model(item)


@mcp.tool()
@tool_errors
def move_item(
    item_id: Annotated[int, Field(description="項目 ID")],
    status: Annotated[Status, Field(description="移動先の状態")],
    reason: Annotated[str, Field(description="理由（履歴に残る・省略可）")] = "",
) -> Item:
    """項目の状態（列）を変える。人間の判断待ちは waiting_human、AI の番は waiting_ai。同じ状態への移動はエラー。"""
    with session() as conn:
        service.ai_get_item(conn, item_id, write=True)
        return Item.from_model(service.move_item(conn, item_id, status, reason=reason, author=author(), source=SOURCE))


@mcp.tool()
@tool_errors
def add_note(
    item_id: Annotated[int, Field(description="項目 ID")],
    body: Annotated[str, Field(min_length=1, max_length=4000, description="ノート本文（Markdown・1〜4000 文字）")],
) -> Note:
    """項目にノートを追記する（編集・削除はできない）。"""
    with session() as conn:
        service.ai_get_item(conn, item_id, write=True)
        return Note.from_model(service.add_note(conn, item_id, body, author=author(), source=SOURCE))


@mcp.tool()
@tool_errors
def complete_item(
    item_id: Annotated[int, Field(description="項目 ID")],
    summary: Annotated[str, Field(description="完了メモ（ノートとして残る・省略可）")] = "",
) -> Item:
    """項目を完了（done）にする。summary があれば完了ノートとして残す。すでに完了ならエラー。"""
    with session() as conn:
        service.ai_get_item(conn, item_id, write=True)
        return Item.from_model(service.complete_item(conn, item_id, summary=summary, author=author(), source=SOURCE))


def main() -> None:
    logging.basicConfig(level=logging.INFO)  # 既定ハンドラは stderr（stdout はプロトコル）
    mcp.run()  # 引数なし = stdio


if __name__ == "__main__":
    main()
