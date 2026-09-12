"""値の決まり（SPEC §3-2）と検証、行→dict 変換。フレームワーク非依存（MCP／REST でも使う）。"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

STATUSES: tuple[str, ...] = ("candidate", "doing", "waiting_human", "waiting_ai", "done", "hold")
STATUS_LABELS: dict[str, str] = {
    "candidate": "候補",
    "doing": "着手",
    "waiting_human": "待ち（人）",
    "waiting_ai": "待ち（AI）",
    "done": "完了",
    "hold": "保留",
}
PRIORITIES: tuple[str, ...] = ("low", "normal", "high", "urgent")
PRIORITY_LABELS: dict[str, str] = {"low": "低", "normal": "通常", "high": "高", "urgent": "至急"}
AI_POLICIES: tuple[str, ...] = ("read_write", "read_only", "hidden")
AI_POLICY_LABELS: dict[str, str] = {"read_write": "AI: 読み書き", "read_only": "AI: 読み取りのみ", "hidden": "AI: 非公開"}
LINK_KINDS: tuple[str, ...] = ("article", "task", "url")
EVENT_KINDS: tuple[str, ...] = (
    "item.created",
    "item.updated",
    "item.moved",
    "item.completed",
    "note.added",
    "workspace.created",
    "workspace.updated",
)
SOURCES: tuple[str, ...] = ("ui", "mcp", "rest", "import")

AUTHOR_RE = re.compile(r"^(human|ai:[a-z0-9][a-z0-9._-]{0,39})$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

TITLE_MAX = 200
NOTE_MAX = 4000


class ValidationError(ValueError):
    """入力の形式違い（HTTP 400 / ToolError 相当）。"""


class NotFound(LookupError):
    """存在しない、または呼び出し元からは見えない（HTTP 404）。"""


class Conflict(RuntimeError):
    """同じ状態への移動・二重完了など（HTTP 409）。"""


def validate_author(author: str) -> str:
    if not isinstance(author, str) or not AUTHOR_RE.match(author):
        raise ValidationError("author must be 'human' or 'ai:<name>' (name: ^[a-z0-9][a-z0-9._-]{0,39}$)")
    return author


def validate_owner(owner: str | None) -> str | None:
    if owner is None or owner == "":
        return None
    return validate_author(owner)


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValidationError("slug must match ^[a-z0-9][a-z0-9-]{0,39}$")
    return slug


def slugify(name: str) -> str:
    """名前から slug の候補を作る（ASCII 英数字以外は落とす。空なら 'ws'）。"""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    s = s[:40].strip("-")
    return s or "ws"


def validate_title(title: str) -> str:
    title = (title or "").strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise ValidationError(f"title must be 1-{TITLE_MAX} characters")
    return title


def validate_status(status: str) -> str:
    if status not in STATUSES:
        raise ValidationError(f"status must be one of {', '.join(STATUSES)}")
    return status


def validate_priority(priority: str) -> str:
    if priority not in PRIORITIES:
        raise ValidationError(f"priority must be one of {', '.join(PRIORITIES)}")
    return priority


def validate_ai_policy(policy: str) -> str:
    if policy not in AI_POLICIES:
        raise ValidationError(f"ai_policy must be one of {', '.join(AI_POLICIES)}")
    return policy


def validate_due(due: str | None) -> str | None:
    if due is None or due == "":
        return None
    if not DUE_RE.match(due):
        raise ValidationError("due must be 'YYYY-MM-DD'")
    try:
        date.fromisoformat(due)
    except ValueError as e:
        raise ValidationError("due must be a real date 'YYYY-MM-DD'") from e
    return due


def validate_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    out: list[str] = []
    for raw in tags or ():
        t = (raw or "").strip().lower()
        if not t:
            continue
        if not TAG_RE.match(t):
            raise ValidationError(f"tag '{raw}' must match ^[a-z0-9][a-z0-9._-]{{0,39}}$ (lowercase)")
        if t not in out:
            out.append(t)
    return out


def parse_tags(text: str) -> list[str]:
    """フォームの 'a, b c' や CSV の 'a;b' を tag リストに。"""
    return validate_tags(re.split(r"[,;\s]+", text or ""))


def validate_links(links: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for raw in links or ():
        kind = (raw.get("kind") or "url").strip()
        target = (raw.get("target") or "").strip()
        label = (raw.get("label") or "").strip()
        if kind not in LINK_KINDS:
            raise ValidationError(f"link.kind must be one of {', '.join(LINK_KINDS)}")
        if not target:
            raise ValidationError("link.target must not be empty")
        if kind == "url" and not re.match(r"^https?://", target):
            raise ValidationError("link.target of kind 'url' must start with http:// or https://")
        if kind == "article" and not target.startswith("/"):
            raise ValidationError("link.target of kind 'article' must be a site path starting with '/'")
        out.append({"kind": kind, "target": target, "label": label})
    return out


def parse_links(text: str) -> list[dict[str, str]]:
    """フォームの 1 行 1 リンク 'kind target label...' を links に。kind 省略時は target から推定。"""
    out: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if parts[0] in LINK_KINDS:
            kind = parts[0]
            rest = parts[1:]
        else:
            rest = line.split(None, 1)
            target0 = rest[0]
            kind = "task" if re.match(r"^t-[0-9a-f]{6,}$", target0) else ("article" if target0.startswith("/") else "url")
        if not rest:
            raise ValidationError(f"link line '{line}' needs a target")
        out.append({"kind": kind, "target": rest[0], "label": rest[1] if len(rest) > 1 else ""})
    return validate_links(out)


@dataclass
class Workspace:
    id: int
    slug: str
    name: str
    description: str
    ai_policy: str
    sort_order: int
    created_at: str
    archived_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Workspace":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "ai_policy": self.ai_policy,
            "archived": self.archived_at is not None,
            "created_at": self.created_at,
        }


@dataclass
class Item:
    id: int
    workspace_id: int
    workspace: str  # slug
    title: str
    body: str
    status: str
    priority: str
    owner: str | None
    due: str | None
    created_by: str
    created_at: str
    updated_at: str
    completed_at: str | None
    sort_order: int
    tags: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)

    @property
    def created_by_ai(self) -> bool:
        return self.created_by.startswith("ai:")

    @property
    def overdue(self) -> bool:
        if not self.due or self.status in ("done", "hold"):
            return False
        return self.due < datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def to_dict(self, base_url: str = "") -> dict[str, Any]:
        """SPEC §3-4 の JSON 表現。url はサーバーが組み立てる。"""
        return {
            "id": self.id,
            "workspace": self.workspace,
            "title": self.title,
            "body": self.body,
            "status": self.status,
            "priority": self.priority,
            "owner": self.owner,
            "due": self.due,
            "tags": list(self.tags),
            "links": [dict(l) for l in self.links],
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "url": f"{base_url}/w/{self.workspace}/items/{self.id}",
        }

    def to_summary(self, base_url: str = "") -> dict[str, Any]:
        d = self.to_dict(base_url)
        d.pop("body")
        return d


@dataclass
class Note:
    id: int
    item_id: int
    body: str
    author: str
    created_at: str

    @property
    def by_ai(self) -> bool:
        return self.author.startswith("ai:")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "item_id": self.item_id, "body": self.body, "author": self.author, "created_at": self.created_at}


@dataclass
class Event:
    id: int
    workspace_id: int
    item_id: int | None
    kind: str
    author: str
    payload: dict[str, Any]
    source: str
    created_at: str

    @property
    def by_ai(self) -> bool:
        return self.author.startswith("ai:")

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "author": self.author,
            "kind": self.kind,
            "item_id": self.item_id,
            "payload": dict(self.payload),
            "source": self.source,
        }
