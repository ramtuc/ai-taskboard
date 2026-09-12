"""MCP ツールと REST が共有する Pydantic モデル（SPEC §3-4 / §4-2）。

- 戻り値を Pydantic モデルにすると MCP SDK が output_schema と structured_content を作る
  （素の dict では付かない — spike/ENV.md の教訓）。REST では response_model にそのまま使う
- ItemSummary は Item から body を抜いたもの（一覧で本文を返すとコンテキストを食うため）
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import models as m

Status = Literal["candidate", "doing", "waiting_human", "waiting_ai", "done", "hold"]
Priority = Literal["low", "normal", "high", "urgent"]
LinkKind = Literal["article", "task", "url"]
AiPolicy = Literal["read_write", "read_only", "hidden"]


def base_url() -> str:
    """AI が人間に渡す URL の土台（サーバーが組み立てて返す・SPEC §3-4）。"""
    return os.environ.get("TASKBOARD_BASE_URL", "http://127.0.0.1:8765").rstrip("/")


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Annotated[LinkKind, Field(description="article=サイト内パス(/posts/...) / task=.ai-team のタスク ID (t-xxxx) / url=それ以外の URL")]
    target: Annotated[str, Field(description="'/posts/xxx/' | 't-xxxx' | 'https://...'")]
    label: Annotated[str, Field(description="表示ラベル（任意）")] = ""


class Item(BaseModel):
    """項目 1 件（SPEC §3-4）。url はサーバーが組み立てる。"""

    id: int
    workspace: str
    title: str
    body: str
    status: Status
    priority: Priority
    owner: str | None
    due: str | None
    tags: list[str]
    links: list[Link]
    created_by: str
    created_at: str
    updated_at: str
    completed_at: str | None
    url: str

    @classmethod
    def from_model(cls, item: m.Item) -> "Item":
        return cls(**item.to_dict(base_url()))


class ItemSummary(BaseModel):
    """Item から body を抜いたもの。"""

    id: int
    workspace: str
    title: str
    status: Status
    priority: Priority
    owner: str | None
    due: str | None
    tags: list[str]
    links: list[Link]
    created_by: str
    created_at: str
    updated_at: str
    completed_at: str | None
    url: str

    @classmethod
    def from_model(cls, item: m.Item) -> "ItemSummary":
        return cls(**item.to_summary(base_url()))


class ItemList(BaseModel):
    items: list[ItemSummary]
    total: int
    next_offset: int | None = Field(description="続きがあれば次の offset、無ければ null")


class Note(BaseModel):
    id: int
    item_id: int
    body: str
    author: str
    created_at: str

    @classmethod
    def from_model(cls, note: m.Note) -> "Note":
        return cls(**note.to_dict())


class EventSummary(BaseModel):
    created_at: str
    author: str
    kind: str
    item_id: int | None
    payload: dict[str, Any]
    source: str

    @classmethod
    def from_model(cls, ev: m.Event) -> "EventSummary":
        return cls(**ev.to_dict())


class ItemDetail(BaseModel):
    item: Item
    notes: list[Note]
    events: list[EventSummary]


class WorkspaceInfo(BaseModel):
    slug: str
    name: str
    description: str
    ai_policy: AiPolicy
    counts: dict[str, int]
    url: str


class WorkspaceList(BaseModel):
    workspaces: list[WorkspaceInfo]


class WorkspaceSummary(BaseModel):
    workspace: str
    name: str
    ai_policy: AiPolicy
    counts: dict[str, int]
    overdue: list[ItemSummary]
    waiting_ai: list[ItemSummary]
    recent_events: list[EventSummary]
    url: str


# ---- REST の入力（MCP はツール引数を直接受ける） ----
class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    priority: Priority = "normal"
    owner: str | None = None
    due: str | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)


class ItemUpdate(BaseModel):
    """PATCH の入力。status を含んでいたら 400（状態は move で変える・SPEC §4-4）。"""

    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    body: str | None = None
    priority: Priority | None = None
    owner: str | None = Field(default=None, description="'' で解除")
    due: str | None = Field(default=None, description="'' で解除")
    tags: list[str] | None = None
    links: list[Link] | None = None


class MoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status
    reason: str = ""


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = ""


def workspace_info(conn, ws: m.Workspace, counts: dict[str, int]) -> WorkspaceInfo:  # noqa: ANN001
    return WorkspaceInfo(
        slug=ws.slug, name=ws.name, description=ws.description, ai_policy=ws.ai_policy, counts=counts, url=f"{base_url()}/w/{ws.slug}"
    )
