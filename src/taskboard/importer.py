"""取り込み（SPEC §7）。JSON が正、CSV が副。

- JSON: {"format":"taskboard-import","version":1,"workspaces":[...],"items":[...]}
  - workspace の slug が無ければ作る
  - 同じタイトルが同じワークスペースにあればスキップして報告（上書きしない）
  - item.created の payload に {"import_file": "<ファイル名>"}、source='import'
  - 拡張（任意）: item に "moves": [{"to": <status>, "author": ..., "reason": ...}] を書くと
    作成後にその順で move_item を適用する（status は「作成時の状態」になる）。デモ DB の履歴作りに使う
- CSV: ヘッダ固定 workspace,title,status,priority,owner,due,tags,body。tags は ';' 区切り。
  本文の改行は '\\n' リテラル。リンク・ノートは CSV では扱わない
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import models as m
from . import service
from .models import NotFound

CSV_HEADER = ["workspace", "title", "status", "priority", "owner", "due", "tags", "body"]


@dataclass
class ImportReport:
    file: str
    dry_run: bool = False
    workspaces_created: list[str] = field(default_factory=list)
    items_created: int = 0
    items_skipped: list[str] = field(default_factory=list)  # "slug: title"
    notes_created: int = 0
    moves_applied: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"file: {self.file}{'  (dry-run: nothing written)' if self.dry_run else ''}",
            f"workspaces created: {len(self.workspaces_created)} {self.workspaces_created}",
            f"items created: {self.items_created}, skipped (duplicate title): {len(self.items_skipped)}",
            f"notes created: {self.notes_created}, moves applied: {self.moves_applied}",
        ]
        for s in self.items_skipped:
            lines.append(f"  skip: {s}")
        for e in self.errors:
            lines.append(f"  error: {e}")
        return "\n".join(lines)


def load_file(path: str | Path) -> dict[str, Any]:
    """JSON か CSV を読んで、JSON 形式（version 1）の dict に正規化する。"""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        return _csv_to_doc(p)
    doc = json.loads(p.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("format") != "taskboard-import":
        raise m.ValidationError("JSON must have \"format\": \"taskboard-import\"")
    if int(doc.get("version", 0)) != 1:
        raise m.ValidationError("unsupported import version (expected 1)")
    return doc


def _csv_to_doc(p: Path) -> dict[str, Any]:
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        if header != CSV_HEADER:
            raise m.ValidationError(f"CSV header must be exactly: {','.join(CSV_HEADER)}")
        items: list[dict[str, Any]] = []
        for row in reader:
            items.append(
                {
                    "workspace": (row.get("workspace") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                    "status": (row.get("status") or "").strip() or "candidate",
                    "priority": (row.get("priority") or "").strip() or "normal",
                    "owner": (row.get("owner") or "").strip() or None,
                    "due": (row.get("due") or "").strip() or None,
                    "tags": [t for t in (row.get("tags") or "").split(";") if t.strip()],
                    "body": (row.get("body") or "").replace("\\n", "\n"),
                }
            )
    return {"format": "taskboard-import", "version": 1, "workspaces": [], "items": items}


def import_doc(
    conn: sqlite3.Connection,
    doc: dict[str, Any],
    *,
    file_label: str,
    default_author: str = "human",
    dry_run: bool = False,
) -> ImportReport:
    report = ImportReport(file=file_label, dry_run=dry_run)
    m.validate_author(default_author)
    payload = {"import_file": file_label}

    if dry_run:
        # service 層は関数ごとに commit するので、dry-run はメモリ上のコピーに対して実行して捨てる
        from .db import connect as _connect

        mem = _connect(":memory:")
        conn.backup(mem)
        try:
            _apply(mem, doc, report, default_author, payload)
        finally:
            mem.close()
        return report
    _apply(conn, doc, report, default_author, payload)
    return report


def _apply(conn: sqlite3.Connection, doc: dict[str, Any], report: ImportReport, default_author: str, payload: dict[str, Any]) -> None:
    for ws in doc.get("workspaces") or []:
        slug = ws.get("slug") or m.slugify(ws.get("name", ""))
        try:
            service.get_workspace(conn, slug)
        except NotFound:
            service.create_workspace(
                conn,
                slug,
                ws.get("name") or slug,
                description=ws.get("description") or "",
                ai_policy=ws.get("ai_policy") or "read_write",
                author=default_author,
                source="import",
            )
            report.workspaces_created.append(slug)

    for raw in doc.get("items") or []:
        slug = (raw.get("workspace") or "").strip()
        if not slug:
            report.errors.append(f"item without workspace: {raw.get('title')!r}")
            continue
        try:
            ws = service.get_workspace(conn, slug)
        except NotFound:
            ws = service.create_workspace(conn, slug, slug, author=default_author, source="import")
            report.workspaces_created.append(slug)
        title = (raw.get("title") or "").strip()
        if conn.execute("SELECT 1 FROM item WHERE workspace_id = ? AND title = ?", (ws.id, title)).fetchone():
            report.items_skipped.append(f"{slug}: {title}")
            continue
        author = raw.get("created_by") or default_author
        try:
            item = service.add_item(
                conn,
                ws.id,
                title,
                body=raw.get("body") or "",
                status=raw.get("status") or "candidate",
                priority=raw.get("priority") or "normal",
                owner=raw.get("owner"),
                due=raw.get("due"),
                tags=raw.get("tags") or [],
                links=raw.get("links") or [],
                author=author,
                source="import",
                event_payload=payload,
            )
        except (m.ValidationError, NotFound) as e:
            report.errors.append(f"{slug}: {title!r}: {e}")
            continue
        report.items_created += 1
        for mv in raw.get("moves") or []:
            try:
                service.move_item(
                    conn,
                    item.id,
                    mv.get("to") or "",
                    reason=mv.get("reason") or "",
                    author=mv.get("author") or author,
                    source="import",
                )
                report.moves_applied += 1
            except (m.ValidationError, m.Conflict) as e:
                report.errors.append(f"{slug}: {title!r}: move: {e}")
        for note in raw.get("notes") or []:
            try:
                service.add_note(conn, item.id, note.get("body") or "", author=note.get("author") or author, source="import")
                report.notes_created += 1
            except m.ValidationError as e:
                report.errors.append(f"{slug}: {title!r}: note: {e}")


def import_file(
    conn: sqlite3.Connection, path: str | Path, *, default_author: str = "human", dry_run: bool = False
) -> ImportReport:
    doc = load_file(path)
    return import_doc(conn, doc, file_label=Path(path).name, default_author=default_author, dry_run=dry_run)
