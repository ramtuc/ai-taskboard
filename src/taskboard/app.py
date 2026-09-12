"""FastAPI アプリ（Web UI）。REST（/api/v1）と MCP は v0.3 で別モジュールに足す。"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__, db, service
from .models import Conflict, Forbidden, NotFound, ValidationError
from .deps import is_htmx
from .render import local_date, local_dt, render_markdown, short_date

PACKAGE_DIR = Path(__file__).resolve().parent
HOST = "127.0.0.1"  # 固定。LAN 公開は v1 スコープ外（SPEC §6-1）
DEFAULT_PORT = 8765

log = logging.getLogger("taskboard")

INITIAL_WORKSPACES = [  # Manager 決定（SPEC §10-2 / §10-8）
    {"slug": "blog", "name": "ブログ", "ai_policy": "read_write"},
    {"slug": "work", "name": "仕事", "ai_policy": "hidden"},
    {"slug": "dev", "name": "開発", "ai_policy": "read_write"},
]


def ensure_initial_workspaces(conn: sqlite3.Connection) -> list[str]:
    """workspace が 1 件も無いときだけ初期の 3 つを作る（データを消して起動しても使える）。"""
    if conn.execute("SELECT COUNT(*) FROM workspace").fetchone()[0]:
        return []
    created = []
    for ws in INITIAL_WORKSPACES:
        service.create_workspace(conn, ws["slug"], ws["name"], ai_policy=ws["ai_policy"], author="human", source="ui")
        created.append(ws["slug"])
    return created


def _run_daily_backup(path: Path) -> None:
    try:
        dest = db.maybe_daily_backup(path)
        if dest:
            log.info("daily backup written: %s", dest)
    except Exception:  # バックアップ失敗でサーバーを止めない
        log.exception("daily backup failed")


async def _backup_loop(path: Path, interval_seconds: float = 3600) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(_run_daily_backup, path)


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))  # autoescape は既定で有効
    templates.env.filters["markdown"] = render_markdown
    templates.env.filters["local_dt"] = local_dt
    templates.env.filters["local_date"] = local_date
    templates.env.filters["short_date"] = short_date
    from . import models as m

    templates.env.globals.update(
        STATUSES=m.STATUSES,
        STATUS_LABELS=m.STATUS_LABELS,
        PRIORITIES=m.PRIORITIES,
        PRIORITY_LABELS=m.PRIORITY_LABELS,
        AI_POLICIES=m.AI_POLICIES,
        AI_POLICY_LABELS=m.AI_POLICY_LABELS,
        app_version=__version__,
    )
    return templates


def create_app(db_path: str | Path | None = None, *, daily_backup: bool = True) -> FastAPI:
    path = Path(db_path) if db_path else db.default_db_path()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.init_db(path)
        try:
            created = ensure_initial_workspaces(conn)
            if created:
                log.info("created initial workspaces: %s", created)
        finally:
            conn.close()
        task = None
        if daily_backup:
            _run_daily_backup(path)  # 起動時に 1 回
            task = asyncio.create_task(_backup_loop(path))  # 以後は 1 時間ごとに「24 時間経っていれば」実行（SPEC §6-3 の簡易スケジューラ）
        try:
            yield
        finally:
            if task:
                task.cancel()

    app = FastAPI(title="ai-taskboard", version=__version__, lifespan=lifespan, docs_url="/docs")
    app.state.db_path = path
    app.state.templates = build_templates()
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    from .api import router as api_router
    from .routes import items, workspaces

    app.include_router(workspaces.router)
    app.include_router(items.router)
    app.include_router(api_router)  # /api/v1（TASKBOARD_API_TOKEN 未設定なら 404 を返す）

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "db": str(path), "version": __version__}

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound):
        return _error_response(request, 404, str(exc))

    @app.exception_handler(ValidationError)
    async def _bad_request(request: Request, exc: ValidationError):
        return _error_response(request, 400, str(exc))

    @app.exception_handler(Conflict)
    async def _conflict(request: Request, exc: Conflict):
        return _error_response(request, 409, str(exc))

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        return _error_response(request, 403, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError):
        # SPEC §4-4: 検証エラーは 400（FastAPI 既定の 422 ではなく）
        return _error_response(request, 400, "; ".join(f"{'.'.join(str(x) for x in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()))

    return app


def _error_response(request: Request, status: int, message: str):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": message}, status_code=status)
    if is_htmx(request):
        # htmx は 4xx を差し込まないので、本文をそのまま #flash に出す（base.html の小さなハンドラ）
        return HTMLResponse(message, status_code=status)
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(request, "error.html", {"status": status, "message": message}, status_code=status)
