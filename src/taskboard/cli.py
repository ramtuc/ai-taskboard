"""`taskboard` コマンド（pyproject の [project.scripts]）。

  uv run taskboard serve [--port 8765] [--db PATH] [--reload]
  uv run taskboard init-db [--db PATH]
  uv run taskboard seed --demo [--db PATH]        # 既定は data/demo.sqlite3（通常 DB とは別ファイル）
  uv run taskboard import FILE.json|FILE.csv [--dry-run] [--author human] [--db PATH]
  uv run taskboard backup [--db PATH] [--keep 30]

--db を省略すると環境変数 TASKBOARD_DB、無ければ data/taskboard.sqlite3。
ホストは 127.0.0.1 固定（LAN 公開は v1 スコープ外。オプションを用意しない）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, db

def seed_dir() -> Path:
    """<repo>/seed（src レイアウト）。見つからなければカレントの seed/。"""
    here = Path(__file__).resolve().parent.parent.parent / "seed"
    return here if here.exists() else Path.cwd() / "seed"


def _db_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", type=Path, default=None, help="SQLite ファイル（既定: $TASKBOARD_DB か data/taskboard.sqlite3）")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taskboard", description="ai-taskboard — 人と AI の候補・残項目ボード")
    p.add_argument("--version", action="version", version=f"ai-taskboard {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Web UI を起動（127.0.0.1 のみ）")
    s.add_argument("--port", type=int, default=None, help="ポート（既定 8765。$TASKBOARD_PORT でも可）")
    s.add_argument("--reload", action="store_true", help="開発用: ソース変更で自動再起動")
    s.add_argument("--no-backup", action="store_true", help="起動時の日次バックアップをしない")
    _db_arg(s)

    s = sub.add_parser("init-db", help="DB を作成／マイグレーションと初期ワークスペースを用意")
    _db_arg(s)

    s = sub.add_parser("seed", help="ダミーデータを投入（--demo）")
    s.add_argument("--demo", action="store_true", required=True, help="seed/demo.json を data/demo.sqlite3 へ")
    s.add_argument("--db", type=Path, default=None, help="投入先（既定: data/demo.sqlite3）")

    s = sub.add_parser("import", help="JSON（正）／CSV（副）を取り込む（SPEC §7）")
    s.add_argument("file", type=Path)
    s.add_argument("--dry-run", action="store_true", help="書き込まずに結果だけ表示")
    s.add_argument("--author", default="human", help="created_by が無い項目の作成者（既定 human）")
    _db_arg(s)

    s = sub.add_parser("backup", help="Connection.backup() で data/backups/ へ")
    s.add_argument("--keep", type=int, default=db.BACKUP_KEEP, help="残す世代数（既定 30）")
    s.add_argument("--dir", type=Path, default=None, help="バックアップ先（既定: DB と同じ場所の backups/）")
    _db_arg(s)
    return p


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn

    from .app import DEFAULT_PORT, HOST, create_app

    port = args.port or int(os.environ.get("TASKBOARD_PORT", DEFAULT_PORT))
    path = args.db or db.default_db_path()
    if args.reload:
        os.environ["TASKBOARD_DB"] = str(path)
        uvicorn.run("taskboard.app:create_app", factory=True, host=HOST, port=port, reload=True, reload_dirs=[str(Path(__file__).parent)])
        return 0
    app = create_app(path, daily_backup=not args.no_backup)
    print(f"ai-taskboard v{__version__}  http://{HOST}:{port}/  db={path}", flush=True)
    uvicorn.run(app, host=HOST, port=port, log_level="info")
    return 0


def cmd_init_db(args: argparse.Namespace) -> int:
    from .app import ensure_initial_workspaces

    path = args.db or db.default_db_path()
    conn = db.init_db(path)
    try:
        created = ensure_initial_workspaces(conn)
        version = db.current_version(conn)
    finally:
        conn.close()
    print(f"db={path} schema_version={version} initial_workspaces={created or '(already present)'}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from .importer import import_file

    path = args.db or db.demo_db_path()
    if path.resolve() == db.default_db_path().resolve():
        print("refusing to seed the primary DB (use --db to name a separate file)", file=sys.stderr)
        return 2
    demo = seed_dir() / "demo.json"
    conn = db.init_db(path)
    try:
        report = import_file(conn, demo, default_author="human")
    finally:
        conn.close()
    print(f"seeded demo data into {path}")
    print(report.summary())
    print(f"\nrun:  TASKBOARD_DB={path} uv run taskboard serve   (PowerShell: $env:TASKBOARD_DB='{path}')")
    return 0 if not report.errors else 1


def cmd_import(args: argparse.Namespace) -> int:
    from .importer import import_file

    path = args.db or db.default_db_path()
    conn = db.init_db(path)
    try:
        report = import_file(conn, args.file, default_author=args.author, dry_run=args.dry_run)
    finally:
        conn.close()
    print(report.summary())
    return 0 if not report.errors else 1


def cmd_backup(args: argparse.Namespace) -> int:
    path = args.db or db.default_db_path()
    if not Path(path).exists():
        print(f"no database at {path}", file=sys.stderr)
        return 2
    dest = db.backup(path, args.dir, keep=args.keep)
    print(f"backup written: {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # Windows の cp932 コンソール対策
        except Exception:
            pass
    handler = {
        "serve": cmd_serve,
        "init-db": cmd_init_db,
        "seed": cmd_seed,
        "import": cmd_import,
        "backup": cmd_backup,
    }[args.cmd]
    try:
        return handler(args)
    except Exception as e:  # 取り込みの形式違いなどは 1 行で
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
