from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from taskboard import db, service
from taskboard.app import create_app, ensure_initial_workspaces


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "test.sqlite3"


@pytest.fixture
def conn(db_path: Path):
    c = db.init_db(db_path)
    ensure_initial_workspaces(c)
    yield c
    c.close()


@pytest.fixture
def blog(conn: sqlite3.Connection):
    return service.get_workspace(conn, "blog")


@pytest.fixture
def client(db_path: Path):
    app = create_app(db_path, daily_backup=False)
    with TestClient(app) as c:  # lifespan で init_db + 初期ワークスペース
        yield c


HX = {"HX-Request": "true"}


def hx(target: str) -> dict[str, str]:
    return {"HX-Request": "true", "HX-Target": target}
