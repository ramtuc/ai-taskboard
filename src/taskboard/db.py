"""SQLite 接続・マイグレーション・バックアップ（SPEC §3-3 / §6-3）。

- 接続ごとに WAL / foreign_keys / busy_timeout を設定する（SQLite の既定は foreign_keys OFF）
- マイグレーションは schema_version を見て migrations/000N_*.sql を前方にだけ適用する最小実装
- バックアップは sqlite3.Connection.backup()（オンラインバックアップ API）で WAL 中でも整合した 1 ファイルを書く
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = PACKAGE_DIR / "migrations"

DEFAULT_DB_NAME = "taskboard.sqlite3"
DEMO_DB_NAME = "demo.sqlite3"
BACKUP_KEEP = 30


def data_dir() -> Path:
    return Path(os.environ.get("TASKBOARD_DATA_DIR", "data"))


def default_db_path() -> Path:
    """環境変数 TASKBOARD_DB があればそれ、無ければ <data_dir>/taskboard.sqlite3。"""
    env = os.environ.get("TASKBOARD_DB")
    return Path(env) if env else data_dir() / DEFAULT_DB_NAME


def demo_db_path() -> Path:
    return data_dir() / DEMO_DB_NAME


def now_utc() -> str:
    """SPEC §3-3 の時刻形式 'YYYY-MM-DDTHH:MM:SSZ'（UTC）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """接続を開き、SPEC §3-3 の PRAGMA を設定する。row_factory は sqlite3.Row。"""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI は依存関係（同期）をスレッドプールで、async ルートをイベントループで動かす。
    # 1 接続は 1 リクエストの中でしか使わないので安全
    conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _migration_files() -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"^(\d{4})_", p.name)
        if m:
            out.append((int(m.group(1)), p))
    return out


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
    if row is None:
        return 0
    v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    return int(v or 0)


def migrate(conn: sqlite3.Connection) -> list[int]:
    """未適用のマイグレーションを順に適用し、適用した版番号を返す。後方には戻さない。"""
    applied: list[int] = []
    version = current_version(conn)
    for number, path in _migration_files():
        if number <= version:
            continue
        sql = path.read_text(encoding="utf-8")
        with conn:
            conn.executescript(sql)
            if number > 1:  # 0001 は自分で schema_version を作って INSERT する
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
        applied.append(number)
        version = number
    return applied


def init_db(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """接続してマイグレーションを当てた接続を返す（data/ を消して起動しても初期化できる）。"""
    conn = connect(path)
    migrate(conn)
    return conn


def backups_dir_for(path: str | os.PathLike[str], backups_dir: str | os.PathLike[str] | None = None) -> Path:
    return Path(backups_dir) if backups_dir else Path(path).parent / "backups"


def backup(
    path: str | os.PathLike[str],
    backups_dir: str | os.PathLike[str] | None = None,
    keep: int = BACKUP_KEEP,
) -> Path:
    """DB を backups/<stem>-YYYYMMDD-HHMM.sqlite3 へオンラインバックアップし、世代を keep 個に保つ。"""
    src_path = Path(path)
    dest_dir = backups_dir_for(src_path, backups_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    dest = dest_dir / f"{src_path.stem}-{stamp}.sqlite3"
    n = 1
    while dest.exists():  # 同じ分に 2 回叩かれたら枝番
        n += 1
        dest = dest_dir / f"{src_path.stem}-{stamp}-{n}.sqlite3"
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    _prune_backups(dest_dir, src_path.stem, keep)
    return dest


def _prune_backups(dest_dir: Path, stem: str, keep: int) -> None:
    files = sorted(dest_dir.glob(f"{stem}-*.sqlite3"), key=lambda p: (p.stat().st_mtime, p.name))
    for old in files[: max(0, len(files) - keep)]:
        old.unlink()


def latest_backup_age_seconds(
    path: str | os.PathLike[str], backups_dir: str | os.PathLike[str] | None = None
) -> float | None:
    src_path = Path(path)
    dest_dir = backups_dir_for(src_path, backups_dir)
    if not dest_dir.exists():
        return None
    files = list(dest_dir.glob(f"{src_path.stem}-*.sqlite3"))
    if not files:
        return None
    newest = max(p.stat().st_mtime for p in files)
    return max(0.0, datetime.now().timestamp() - newest)


def maybe_daily_backup(
    path: str | os.PathLike[str], backups_dir: str | os.PathLike[str] | None = None
) -> Path | None:
    """直近のバックアップが 24 時間より古い（または無い）ときだけバックアップする（起動時・日次用）。"""
    if not Path(path).exists():
        return None
    age = latest_backup_age_seconds(path, backups_dir)
    if age is not None and age < 24 * 3600:
        return None
    return backup(path, backups_dir)
