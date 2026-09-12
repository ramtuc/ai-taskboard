"""web_spike の自動テスト (Starlette TestClient・サーバ起動不要)。
実行: uv run --directory E:/prog/ai-taskboard/spike --with pytest python -m pytest -q tests
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import web_spike  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _client(tmp_path):
    web_spike.DB_PATH = tmp_path / "t.db"  # テストごとに空 DB
    return TestClient(web_spike.app)


def test_index_serves_local_htmx(tmp_path):
    with _client(tmp_path) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert 'src="/static/htmx.min.js"' in r.text
        assert 'hx-post="/items"' in r.text
        assert c.get("/static/htmx.min.js").status_code == 200


def test_hx_post_returns_partial_and_escapes(tmp_path):
    with _client(tmp_path) as c:
        r = c.post("/items", data={"title": "日本語 ✓ <b>x</b>", "author": "ai:test"}, headers={"HX-Request": "true"})
        assert r.status_code == 200
        assert r.text.lstrip().startswith('<ul id="item-list">')  # 部分テンプレートのみ
        assert "<html" not in r.text
        assert "日本語 ✓ &lt;b&gt;x&lt;/b&gt;" in r.text  # autoescape
        assert c.get("/api/items").json()[0]["title"] == "日本語 ✓ <b>x</b>"


def test_blank_title_not_inserted(tmp_path):
    with _client(tmp_path) as c:
        c.post("/items", data={"title": "   "})
        assert c.get("/api/items").json() == []


def test_binds_localhost_only():
    assert web_spike.HOST == "127.0.0.1"
