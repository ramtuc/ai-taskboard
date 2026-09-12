"""Web UI（TestClient）: 各画面 200・追加/移動/ノート/完了・hidden の表示・autoescape・localhost 固定。"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from taskboard import app as app_module
from taskboard.cli import build_parser

from .conftest import HX, hx


def test_index_and_initial_workspaces(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    for slug, name in (("blog", "ブログ"), ("work", "仕事"), ("dev", "開発")):
        assert f"/w/{slug}" in r.text and name in r.text
    assert "AI: 非公開" in r.text  # work は hidden だが UI には普通に出る
    assert 'src="/static/htmx.min.js"' in r.text
    assert client.get("/static/htmx.min.js").status_code == 200


def test_healthz(client: TestClient):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["db"]


def test_board_kanban_and_list(client: TestClient):
    r = client.get("/w/blog")
    assert r.status_code == 200
    assert r.text.count('class="column column-') == 6
    for label in ("候補", "着手", "待ち（人）", "待ち（AI）", "完了", "保留"):
        assert label in r.text
    r = client.get("/w/blog?view=list")
    assert r.status_code == 200 and '<table class="list">' in r.text
    assert client.get("/w/nope").status_code == 404
    assert client.get("/w/work").status_code == 200  # hidden も UI では見える


def test_quick_add_htmx_returns_board_partial(client: TestClient):
    r = client.post("/w/blog/items", data={"title": "日本語の候補 ✓", "view": "kanban"}, headers=hx("board"))
    assert r.status_code == 200
    assert r.text.lstrip().startswith('<section id="board"')
    assert "<html" not in r.text and "日本語の候補 ✓" in r.text
    # author は human・event に記録
    m = re.search(r"/w/blog/items/(\d+)", r.text)
    assert m
    d = client.get(f"/w/blog/items/{m.group(1)}")
    assert d.status_code == 200 and "item.created" in d.text and 'class="badge badge-human"' in d.text


def test_quick_add_plain_form_redirects(client: TestClient):
    r = client.post("/w/blog/items", data={"title": "no js"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/w/blog"
    r = client.post("/w/blog/items", data={"title": "   "}, headers=HX)
    assert r.status_code == 400 and "title" in r.text


def _add(client: TestClient, slug="blog", title="x") -> int:
    r = client.post(f"/w/{slug}/items", data={"title": title}, headers=hx("board"))
    return int(re.search(rf"/w/{slug}/items/(\d+)", r.text).group(1))


def test_move_and_complete_via_board_and_detail(client: TestClient):
    item_id = _add(client)
    r = client.post(f"/items/{item_id}/move", data={"status": "doing", "view": "kanban"}, headers=hx("board"))
    assert r.status_code == 200 and r.text.lstrip().startswith('<section id="board"')
    r = client.post(f"/items/{item_id}/move", data={"status": "doing"}, headers=hx("board"))
    assert r.status_code == 409  # 同じ状態
    r = client.post(f"/items/{item_id}/move", data={"status": "waiting_human", "back": f"/w/blog/items/{item_id}"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/w/blog/items/{item_id}"
    r = client.post(f"/items/{item_id}/complete", data={"summary": "done!"}, headers=hx("detail"))
    assert r.status_code == 200 and r.text.lstrip().startswith('<section id="detail"')
    assert "item.completed" in r.text and "done!" in r.text and "候補 → 着手" in r.text
    assert "完了にする" not in r.text  # done なので完了ボタンは出ない


def test_notes_markdown_and_autoescape(client: TestClient):
    item_id = _add(client)
    r = client.post(f"/items/{item_id}/notes", data={"body": "**太字** <script>alert(1)</script> [x](javascript:alert(2))"}, headers=hx("detail"))
    assert r.status_code == 200
    assert "<strong>太字</strong>" in r.text
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    assert "javascript:alert(2)" not in r.text.replace("[x](javascript:alert(2))", "")
    assert "note.added" in r.text
    r = client.post(f"/items/{item_id}/notes", data={"body": " "}, headers=hx("detail"))
    assert r.status_code == 400


def test_edit_form_and_save(client: TestClient):
    item_id = _add(client, title="<b>title</b>")
    r = client.get(f"/w/blog/items/{item_id}")
    assert "&lt;b&gt;title&lt;/b&gt;" in r.text and "<b>title</b>" not in r.text  # autoescape
    r = client.get(f"/w/blog/items/{item_id}/edit", headers=hx("detail"))
    assert r.status_code == 200 and r.text.lstrip().startswith('<section id="detail" class="detail edit"')
    data = {
        "title": "edited",
        "body": "# 見出し\n\n<img src=x onerror=alert(1)>",
        "priority": "high",
        "owner": "ai:demo-assistant",
        "due": "2026-12-01",
        "tags": "IC-lab, ne555",
        "links": "article /posts/demo/ 前作\ntask t-demo0001\nhttps://example.com ラベル",
    }
    r = client.post(f"/w/blog/items/{item_id}/edit", data=data, headers=hx("detail"))
    assert r.status_code == 200 and "<h1>edited</h1>" in r.text
    assert "<h1>見出し</h1>" in r.text
    assert "<img src=x" not in r.text and "&lt;img src=x onerror=alert(1)&gt;" in r.text  # 生 HTML はエスケープ
    assert "ic-lab" in r.text and "t-demo0001" in r.text and 'href="https://example.com"' in r.text
    assert "item.updated" in r.text
    # 状態はフォームからは変えられない（フィールド自体が無い）→ 検証: status を送っても無視される
    r = client.post(f"/w/blog/items/{item_id}/edit", data={**data, "status": "done"}, follow_redirects=False)
    assert r.status_code == 303
    assert "status-candidate" in client.get(f"/w/blog/items/{item_id}").text
    # 形式違いはフォームにエラー
    r = client.post(f"/w/blog/items/{item_id}/edit", data={**data, "due": "2026-99-99"}, follow_redirects=False)
    assert r.status_code == 400 and "due" in r.text


def test_slug_mismatch_is_404(client: TestClient):
    item_id = _add(client, slug="blog")
    assert client.get(f"/w/dev/items/{item_id}").status_code == 404
    assert client.get(f"/w/blog/items/{item_id}").status_code == 200
    assert client.get("/w/blog/items/99999").status_code == 404


def test_workspace_new_and_settings(client: TestClient):
    r = client.get("/workspaces/new")
    assert r.status_code == 200
    r = client.post("/workspaces/new", data={"name": "実験室", "slug": "", "ai_policy": "read_only"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/w/ws"  # 日本語名は slugify で 'ws'
    r = client.post("/workspaces/new", data={"name": "Lab 2", "ai_policy": "read_write"}, follow_redirects=False)
    assert r.headers["location"] == "/w/lab-2"
    r = client.post("/workspaces/new", data={"name": "dup", "slug": "lab-2"})
    assert r.status_code == 400 and "already exists" in r.text
    r = client.get("/w/lab-2/settings")
    assert r.status_code == 200
    r = client.post("/w/lab-2/settings", data={"name": "Lab 2", "description": "d", "ai_policy": "hidden", "archived": ""})
    assert r.status_code == 200 and "保存しました" in r.text
    assert "AI: 非公開" in client.get("/w/lab-2").text
    r = client.post("/w/lab-2/settings", data={"name": "Lab 2", "ai_policy": "hidden", "archived": "1"})
    assert r.status_code == 200
    idx = client.get("/").text
    assert "アーカイブ済み" in idx


def test_filters_and_list_view(client: TestClient):
    a = _add(client, title="alpha one")
    b = _add(client, title="beta two")
    client.post(f"/items/{b}/move", data={"status": "doing"}, headers=hx("board"))
    r = client.get("/w/blog?view=list&status=doing")
    assert r.status_code == 200 and "beta two" in r.text and "alpha one" not in r.text
    r = client.get("/w/blog?q=alpha", headers=hx("board"))
    assert r.text.lstrip().startswith('<section id="board"') and "alpha one" in r.text and "beta two" not in r.text
    r = client.get("/w/blog?view=list&sort=priority&page=1")
    assert r.status_code == 200 and "2 件 · ページ 1/1" in r.text


def test_localhost_only():
    assert app_module.HOST == "127.0.0.1"
    # serve サブコマンドに --host は無い（LAN 公開は v1 スコープ外）
    parser = build_parser()
    args = parser.parse_args(["serve", "--port", "8123"])
    assert not hasattr(args, "host") and args.port == 8123
