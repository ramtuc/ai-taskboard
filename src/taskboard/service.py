"""service 層 — 唯一の書き込み経路（SPEC §4-1）。UI・REST・MCP はすべてここを呼ぶ。

- 書き込み系は必ず event を同じトランザクションで残す（呼び出し側が忘れられない）
- author は呼び出し側が渡す（UI は 'human'、MCP は環境変数、REST はヘッダ）。source も同様
- 例外: models.NotFound / models.ValidationError / models.Forbidden / models.Conflict（HTTP 404/400/403/409・MCP では ToolError）
- ai_policy の強制（hidden＝存在しない・read_only＝書けない）は MCP／REST が `ai_get_workspace()` / `ai_get_item()` を
  入口で呼ぶことで行う（UI は for_ai=False の関数を使うので全部見える）
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from . import models as m
from .db import now_utc
from .models import Conflict, Event, Forbidden, Item, NotFound, Note, ValidationError, Workspace

DONE_COLUMN_LIMIT = 20  # かんばんの「完了」列に出す件数（SPEC §2-3）


# ---------------------------------------------------------------------------
# event
# ---------------------------------------------------------------------------
def _log_event(
    conn: sqlite3.Connection,
    workspace_id: int,
    item_id: int | None,
    kind: str,
    author: str,
    payload: dict[str, Any],
    source: str,
) -> int:
    if kind not in m.EVENT_KINDS:
        raise ValidationError(f"unknown event kind {kind}")
    if source not in m.SOURCES:
        raise ValidationError(f"unknown source {source}")
    cur = conn.execute(
        "INSERT INTO event (workspace_id, item_id, kind, author, payload, source, created_at) VALUES (?,?,?,?,?,?,?)",
        (workspace_id, item_id, kind, author, json.dumps(payload, ensure_ascii=False), source, now_utc()),
    )
    return int(cur.lastrowid)


def _event_from_row(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        workspace_id=row["workspace_id"],
        item_id=row["item_id"],
        kind=row["kind"],
        author=row["author"],
        payload=json.loads(row["payload"] or "{}"),
        source=row["source"],
        created_at=row["created_at"],
    )


def list_events(
    conn: sqlite3.Connection,
    workspace_id: int | None = None,
    item_id: int | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[Event]:
    """新しい順。"""
    where: list[str] = []
    params: list[Any] = []
    if workspace_id is not None:
        where.append("workspace_id = ?")
        params.append(workspace_id)
    if item_id is not None:
        where.append("item_id = ?")
        params.append(item_id)
    if since:
        where.append("created_at >= ?")
        params.append(since)
    sql = "SELECT * FROM event"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return [_event_from_row(r) for r in conn.execute(sql, params)]


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------
def list_workspaces(conn: sqlite3.Connection, include_archived: bool = False, for_ai: bool = False) -> list[Workspace]:
    """for_ai=True なら hidden を「存在しないもの」として除く（SPEC §4-2）。"""
    sql = "SELECT * FROM workspace"
    where: list[str] = []
    if not include_archived:
        where.append("archived_at IS NULL")
    if for_ai:
        where.append("ai_policy != 'hidden'")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY sort_order, id"
    return [Workspace.from_row(r) for r in conn.execute(sql)]


def get_workspace(conn: sqlite3.Connection, slug: str, for_ai: bool = False) -> Workspace:
    row = conn.execute("SELECT * FROM workspace WHERE slug = ?", (slug,)).fetchone()
    if row is None or (for_ai and row["ai_policy"] == "hidden"):
        raise NotFound(f"workspace '{slug}' not found")
    return Workspace.from_row(row)


def get_workspace_by_id(conn: sqlite3.Connection, workspace_id: int) -> Workspace:
    row = conn.execute("SELECT * FROM workspace WHERE id = ?", (workspace_id,)).fetchone()
    if row is None:
        raise NotFound(f"workspace #{workspace_id} not found")
    return Workspace.from_row(row)


def check_ai_writable(ws: Workspace) -> None:
    """MCP／REST の書き込み系が呼ぶ。hidden は「存在しない」、read_only は Forbidden（403 / ToolError）。"""
    if ws.ai_policy == "hidden":
        raise NotFound(f"workspace '{ws.slug}' not found")
    if ws.ai_policy == "read_only":
        raise Forbidden(f"workspace '{ws.slug}' is read-only for AI")


# ---- AI 側（MCP／REST）の入口。hidden は存在しない扱い・read_only は書けない（SPEC §4-2 / §6-2） ----
def ai_get_workspace(conn: sqlite3.Connection, slug: str, *, write: bool = False) -> Workspace:
    ws = get_workspace(conn, slug, for_ai=True)
    if write:
        check_ai_writable(ws)
    return ws


def ai_get_item(conn: sqlite3.Connection, item_id: int, *, write: bool = False) -> Item:
    item = get_item(conn, item_id, for_ai=True)
    if write:
        check_ai_writable(get_workspace_by_id(conn, item.workspace_id))
    return item


def create_workspace(
    conn: sqlite3.Connection,
    slug: str,
    name: str,
    *,
    description: str = "",
    ai_policy: str = "read_write",
    author: str,
    source: str,
) -> Workspace:
    slug = m.validate_slug(slug)
    name = (name or "").strip()
    if not name:
        raise ValidationError("name must not be empty")
    ai_policy = m.validate_ai_policy(ai_policy)
    m.validate_author(author)
    if conn.execute("SELECT 1 FROM workspace WHERE slug = ?", (slug,)).fetchone():
        raise Conflict(f"workspace '{slug}' already exists")
    with conn:
        order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM workspace").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO workspace (slug, name, description, ai_policy, sort_order, created_at) VALUES (?,?,?,?,?,?)",
            (slug, name, description or "", ai_policy, order, now_utc()),
        )
        wid = int(cur.lastrowid)
        _log_event(conn, wid, None, "workspace.created", author, {"slug": slug, "name": name, "ai_policy": ai_policy}, source)
    return get_workspace(conn, slug)


def update_workspace(
    conn: sqlite3.Connection,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    ai_policy: str | None = None,
    archived: bool | None = None,
    author: str,
    source: str,
) -> Workspace:
    ws = get_workspace(conn, slug)
    m.validate_author(author)
    changes: dict[str, Any] = {}
    sets: list[str] = []
    params: list[Any] = []
    if name is not None and name.strip() != ws.name:
        if not name.strip():
            raise ValidationError("name must not be empty")
        sets.append("name = ?")
        params.append(name.strip())
        changes["name"] = {"from": ws.name, "to": name.strip()}
    if description is not None and description != ws.description:
        sets.append("description = ?")
        params.append(description)
        changes["description"] = {"from": ws.description, "to": description}
    if ai_policy is not None and ai_policy != ws.ai_policy:
        m.validate_ai_policy(ai_policy)
        sets.append("ai_policy = ?")
        params.append(ai_policy)
        changes["ai_policy"] = {"from": ws.ai_policy, "to": ai_policy}
    if archived is not None and archived != (ws.archived_at is not None):
        sets.append("archived_at = ?")
        params.append(now_utc() if archived else None)
        changes["archived"] = {"from": ws.archived_at is not None, "to": archived}
    if not sets:
        return ws
    params.append(ws.id)
    with conn:
        conn.execute(f"UPDATE workspace SET {', '.join(sets)} WHERE id = ?", params)
        _log_event(conn, ws.id, None, "workspace.updated", author, changes, source)
    return get_workspace(conn, slug)


def workspace_counts(conn: sqlite3.Connection, workspace_id: int) -> dict[str, int]:
    counts = {s: 0 for s in m.STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM item WHERE workspace_id = ? GROUP BY status", (workspace_id,)):
        counts[row["status"]] = row["n"]
    return counts


def workspace_last_activity(conn: sqlite3.Connection, workspace_id: int) -> str | None:
    row = conn.execute("SELECT MAX(created_at) FROM event WHERE workspace_id = ?", (workspace_id,)).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# item
# ---------------------------------------------------------------------------
def _tags_for(conn: sqlite3.Connection, item_ids: Iterable[int]) -> dict[int, list[str]]:
    ids = list(item_ids)
    out: dict[int, list[str]] = {i: [] for i in ids}
    if not ids:
        return out
    q = ",".join("?" * len(ids))
    for row in conn.execute(f"SELECT item_id, tag FROM item_tag WHERE item_id IN ({q}) ORDER BY tag", ids):
        out[row["item_id"]].append(row["tag"])
    return out


def _links_for(conn: sqlite3.Connection, item_ids: Iterable[int]) -> dict[int, list[dict[str, str]]]:
    ids = list(item_ids)
    out: dict[int, list[dict[str, str]]] = {i: [] for i in ids}
    if not ids:
        return out
    q = ",".join("?" * len(ids))
    for row in conn.execute(f"SELECT item_id, kind, target, label FROM item_link WHERE item_id IN ({q}) ORDER BY id", ids):
        out[row["item_id"]].append({"kind": row["kind"], "target": row["target"], "label": row["label"]})
    return out


_ITEM_SELECT = "SELECT i.*, w.slug AS workspace FROM item i JOIN workspace w ON w.id = i.workspace_id"


def _items_from_rows(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Item]:
    ids = [r["id"] for r in rows]
    tags = _tags_for(conn, ids)
    links = _links_for(conn, ids)
    items: list[Item] = []
    for r in rows:
        items.append(
            Item(
                id=r["id"],
                workspace_id=r["workspace_id"],
                workspace=r["workspace"],
                title=r["title"],
                body=r["body"],
                status=r["status"],
                priority=r["priority"],
                owner=r["owner"],
                due=r["due"],
                created_by=r["created_by"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                completed_at=r["completed_at"],
                sort_order=r["sort_order"],
                tags=tags[r["id"]],
                links=links[r["id"]],
            )
        )
    return items


def get_item(conn: sqlite3.Connection, item_id: int, for_ai: bool = False) -> Item:
    row = conn.execute(_ITEM_SELECT + " WHERE i.id = ?", (item_id,)).fetchone()
    if row is None:
        raise NotFound(f"item #{item_id} not found")
    if for_ai:
        ws = get_workspace_by_id(conn, row["workspace_id"])
        if ws.ai_policy == "hidden":
            raise NotFound(f"item #{item_id} not found")
    return _items_from_rows(conn, [row])[0]


def list_items(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    status: str | None = None,
    tag: str | None = None,
    owner: str | None = None,
    query: str | None = None,
    sort: str = "updated",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Item], int]:
    """(items, total)。sort は updated / created / due / priority / id / column（列内の並び）。"""
    where = ["i.workspace_id = ?"]
    params: list[Any] = [workspace_id]
    if status:
        where.append("i.status = ?")
        params.append(m.validate_status(status))
    if tag:
        where.append("i.id IN (SELECT item_id FROM item_tag WHERE tag = ?)")
        params.append(tag.strip().lower())
    if owner:
        if owner == "none":
            where.append("i.owner IS NULL")
        else:
            where.append("i.owner = ?")
            params.append(owner)
    if query:
        like = f"%{query.strip()}%"
        where.append("(i.title LIKE ? OR i.body LIKE ?)")
        params.extend([like, like])
    order = {
        "updated": "i.updated_at DESC, i.id DESC",
        "created": "i.created_at DESC, i.id DESC",
        "due": "CASE WHEN i.due IS NULL THEN 1 ELSE 0 END, i.due ASC, i.id DESC",
        "priority": "CASE i.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, i.updated_at DESC",
        "id": "i.id ASC",
        "column": "i.sort_order ASC, i.id DESC",
    }.get(sort, "i.updated_at DESC, i.id DESC")
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM item i WHERE {where_sql}", params).fetchone()[0]
    rows = conn.execute(f"{_ITEM_SELECT} WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    return _items_from_rows(conn, rows), int(total)


def board_columns(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    tag: str | None = None,
    owner: str | None = None,
    query: str | None = None,
) -> dict[str, dict[str, Any]]:
    """かんばん用: 状態ごとに {items, total, truncated}。完了列は直近 DONE_COLUMN_LIMIT 件だけ。"""
    columns: dict[str, dict[str, Any]] = {}
    for s in m.STATUSES:
        limit = DONE_COLUMN_LIMIT if s == "done" else 200
        sort = "updated" if s == "done" else "column"
        items, total = list_items(conn, workspace_id, status=s, tag=tag, owner=owner, query=query, sort=sort, limit=limit)
        columns[s] = {"items": items, "total": total, "truncated": total > len(items)}
    return columns


def _replace_tags(conn: sqlite3.Connection, item_id: int, tags: list[str]) -> None:
    conn.execute("DELETE FROM item_tag WHERE item_id = ?", (item_id,))
    conn.executemany("INSERT INTO item_tag (item_id, tag) VALUES (?, ?)", [(item_id, t) for t in tags])


def _replace_links(conn: sqlite3.Connection, item_id: int, links: list[dict[str, str]]) -> None:
    conn.execute("DELETE FROM item_link WHERE item_id = ?", (item_id,))
    conn.executemany(
        "INSERT INTO item_link (item_id, kind, target, label) VALUES (?,?,?,?)",
        [(item_id, l["kind"], l["target"], l.get("label", "")) for l in links],
    )


def _top_sort_order(conn: sqlite3.Connection, workspace_id: int, status: str) -> int:
    """列の先頭＝現在の最小値 − 1（SPEC §3-3 設計メモ）。"""
    row = conn.execute("SELECT MIN(sort_order) FROM item WHERE workspace_id = ? AND status = ?", (workspace_id, status)).fetchone()
    return int(row[0]) - 1 if row[0] is not None else 0


def add_item(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    *,
    body: str = "",
    status: str = "candidate",
    priority: str = "normal",
    owner: str | None = None,
    due: str | None = None,
    tags: list[str] | None = None,
    links: list[dict[str, Any]] | None = None,
    author: str,
    source: str,
    event_payload: dict[str, Any] | None = None,
) -> Item:
    title = m.validate_title(title)
    status = m.validate_status(status)
    priority = m.validate_priority(priority)
    owner = m.validate_owner(owner)
    due = m.validate_due(due)
    tags = m.validate_tags(tags)
    links = m.validate_links(links)
    m.validate_author(author)
    get_workspace_by_id(conn, workspace_id)
    now = now_utc()
    with conn:
        cur = conn.execute(
            "INSERT INTO item (workspace_id, title, body, status, priority, owner, due, created_by, created_at, updated_at, completed_at, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                workspace_id,
                title,
                body or "",
                status,
                priority,
                owner,
                due,
                author,
                now,
                now,
                now if status == "done" else None,
                _top_sort_order(conn, workspace_id, status),
            ),
        )
        item_id = int(cur.lastrowid)
        _replace_tags(conn, item_id, tags)
        _replace_links(conn, item_id, links)
        payload = {"title": title, "status": status}
        if event_payload:
            payload.update(event_payload)
        _log_event(conn, workspace_id, item_id, "item.created", author, payload, source)
    return get_item(conn, item_id)


_UNSET: Any = object()


def update_item(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    title: str = _UNSET,
    body: str = _UNSET,
    priority: str = _UNSET,
    owner: str | None = _UNSET,
    due: str | None = _UNSET,
    tags: list[str] | None = _UNSET,
    links: list[dict[str, Any]] | None = _UNSET,
    author: str,
    source: str,
) -> Item:
    """status は受けない（状態変更は move_item だけ・SPEC §2-5）。変更が無ければ Conflict。"""
    item = get_item(conn, item_id)
    m.validate_author(author)
    sets: list[str] = []
    params: list[Any] = []
    changed: list[str] = []
    new_tags = new_links = None
    if title is not _UNSET:
        title = m.validate_title(title)
        if title != item.title:
            sets.append("title = ?")
            params.append(title)
            changed.append("title")
    if body is not _UNSET and (body or "") != item.body:
        sets.append("body = ?")
        params.append(body or "")
        changed.append("body")
    if priority is not _UNSET:
        priority = m.validate_priority(priority)
        if priority != item.priority:
            sets.append("priority = ?")
            params.append(priority)
            changed.append("priority")
    if owner is not _UNSET:
        owner = m.validate_owner(owner)
        if owner != item.owner:
            sets.append("owner = ?")
            params.append(owner)
            changed.append("owner")
    if due is not _UNSET:
        due = m.validate_due(due)
        if due != item.due:
            sets.append("due = ?")
            params.append(due)
            changed.append("due")
    if tags is not _UNSET:
        new_tags = m.validate_tags(tags)
        if new_tags != item.tags:
            changed.append("tags")
        else:
            new_tags = None
    if links is not _UNSET:
        new_links = m.validate_links(links)
        if new_links != item.links:
            changed.append("links")
        else:
            new_links = None
    if not changed:
        raise Conflict("nothing to update")
    with conn:
        if sets:
            params.extend([now_utc(), item_id])
            conn.execute(f"UPDATE item SET {', '.join(sets)}, updated_at = ? WHERE id = ?", params)
        else:
            conn.execute("UPDATE item SET updated_at = ? WHERE id = ?", (now_utc(), item_id))
        if new_tags is not None:
            _replace_tags(conn, item_id, new_tags)
        if new_links is not None:
            _replace_links(conn, item_id, new_links)
        # payload は変更したフィールド名だけ（本文は入れない・SPEC §6-2）
        _log_event(conn, item.workspace_id, item_id, "item.updated", author, {"fields": changed}, source)
    return get_item(conn, item_id)


def move_item(
    conn: sqlite3.Connection,
    item_id: int,
    status: str,
    *,
    reason: str = "",
    author: str,
    source: str,
    _kind: str = "item.moved",
) -> Item:
    item = get_item(conn, item_id)
    status = m.validate_status(status)
    m.validate_author(author)
    if status == item.status:
        raise Conflict(f"item #{item_id} is already '{status}'")
    now = now_utc()
    completed_at = now if status == "done" else None
    with conn:
        conn.execute(
            "UPDATE item SET status = ?, completed_at = ?, sort_order = ?, updated_at = ? WHERE id = ?",
            (status, completed_at, _top_sort_order(conn, item.workspace_id, status), now, item_id),
        )
        _log_event(conn, item.workspace_id, item_id, _kind, author, {"from": item.status, "to": status, "reason": reason or ""}, source)
    return get_item(conn, item_id)


def complete_item(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    summary: str = "",
    author: str,
    source: str,
) -> Item:
    """move_item(status='done') の糖衣。summary があれば完了ノートとして残す。"""
    item = get_item(conn, item_id)
    if item.status == "done":
        raise Conflict(f"item #{item_id} is already done")
    if summary and summary.strip():
        add_note(conn, item_id, summary, author=author, source=source)
    return move_item(conn, item_id, "done", reason=summary or "", author=author, source=source, _kind="item.completed")


# ---------------------------------------------------------------------------
# note
# ---------------------------------------------------------------------------
def add_note(conn: sqlite3.Connection, item_id: int, body: str, *, author: str, source: str) -> Note:
    item = get_item(conn, item_id)
    body = (body or "").strip()
    if not 1 <= len(body) <= m.NOTE_MAX:
        raise ValidationError(f"note body must be 1-{m.NOTE_MAX} characters")
    m.validate_author(author)
    now = now_utc()
    with conn:
        cur = conn.execute("INSERT INTO note (item_id, body, author, created_at) VALUES (?,?,?,?)", (item_id, body, author, now))
        note_id = int(cur.lastrowid)
        conn.execute("UPDATE item SET updated_at = ? WHERE id = ?", (now, item_id))
        _log_event(conn, item.workspace_id, item_id, "note.added", author, {"note_id": note_id}, source)
    row = conn.execute("SELECT * FROM note WHERE id = ?", (note_id,)).fetchone()
    return Note(**{k: row[k] for k in Note.__dataclass_fields__})


def list_notes(conn: sqlite3.Connection, item_id: int) -> list[Note]:
    rows = conn.execute("SELECT * FROM note WHERE item_id = ? ORDER BY created_at, id", (item_id,)).fetchall()
    return [Note(**{k: r[k] for k in Note.__dataclass_fields__}) for r in rows]


# ---------------------------------------------------------------------------
# summary（v0.3 の get_workspace_summary が使う）
# ---------------------------------------------------------------------------
def workspace_summary(conn: sqlite3.Connection, ws: Workspace, base_url: str = "") -> dict[str, Any]:
    counts = workspace_counts(conn, ws.id)
    items, _ = list_items(conn, ws.id, sort="due", limit=200)
    overdue = [i.to_summary(base_url) for i in items if i.overdue]
    waiting_ai, _ = list_items(conn, ws.id, status="waiting_ai", sort="column", limit=200)
    events = list_events(conn, workspace_id=ws.id, limit=20)
    return {
        "workspace": ws.slug,
        "name": ws.name,
        "ai_policy": ws.ai_policy,
        "counts": counts,
        "overdue": overdue,
        "waiting_ai": [i.to_summary(base_url) for i in waiting_ai],
        "recent_events": [e.to_dict() for e in events],
        "url": f"{base_url}/w/{ws.slug}",
    }


def all_tags(conn: sqlite3.Connection, workspace_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT t.tag FROM item_tag t JOIN item i ON i.id = t.item_id WHERE i.workspace_id = ? ORDER BY t.tag",
        (workspace_id,),
    )
    return [r["tag"] for r in rows]


def all_owners(conn: sqlite3.Connection, workspace_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT owner FROM item WHERE workspace_id = ? AND owner IS NOT NULL ORDER BY owner", (workspace_id,)
    )
    return [r["owner"] for r in rows]
