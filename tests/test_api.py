"""REST /api/v1: Bearer（未設定=404・不正=401）・X-Taskboard-Author（400）・ai_policy（404/403）・409・監査 events。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from taskboard import db, service
from taskboard.app import create_app, ensure_initial_workspaces

TOKEN = "test-token-not-a-secret"
H = {"Authorization": f"Bearer {TOKEN}", "X-Taskboard-Author": "ai:gemini-analytics"}


@pytest.fixture
def api(db_path: Path, monkeypatch):
    monkeypatch.setenv("TASKBOARD_API_TOKEN", TOKEN)
    monkeypatch.setenv("TASKBOARD_BASE_URL", "http://127.0.0.1:8765")
    conn = db.init_db(db_path)
    ensure_initial_workspaces(conn)
    service.create_workspace(conn, "ro", "読み取り専用", ai_policy="read_only", author="human", source="ui")
    ro = service.get_workspace(conn, "ro")
    service.add_item(conn, ro.id, "ro の項目", author="human", source="ui")
    work = service.get_workspace(conn, "work")
    service.add_item(conn, work.id, "仕事（hidden）", author="human", source="ui")
    conn.close()
    with TestClient(create_app(db_path, daily_backup=False)) as c:
        yield c


def test_rest_disabled_without_token(db_path: Path, monkeypatch):
    monkeypatch.delenv("TASKBOARD_API_TOKEN", raising=False)
    with TestClient(create_app(db_path, daily_backup=False)) as c:
        r = c.get("/api/v1/workspaces", headers=H)
        assert r.status_code == 404 and "TASKBOARD_API_TOKEN" in r.json()["detail"]
        assert c.get("/w/blog").status_code == 200  # UI は動く


def test_auth_and_author_headers(api: TestClient):
    assert api.get("/api/v1/workspaces").status_code == 401
    assert api.get("/api/v1/workspaces", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = api.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 400 and "X-Taskboard-Author" in r.json()["detail"]
    r = api.get("/api/v1/workspaces", headers={"Authorization": f"Bearer {TOKEN}", "X-Taskboard-Author": "gemini"})
    assert r.status_code == 400
    r = api.get("/api/v1/workspaces", headers=H)
    assert r.status_code == 200
    slugs = [w["slug"] for w in r.json()["workspaces"]]
    assert "blog" in slugs and "work" not in slugs  # hidden は出ない


def test_hidden_is_404_and_read_only_is_403(api: TestClient):
    assert api.get("/api/v1/workspaces/work/summary", headers=H).status_code == 404
    assert api.get("/api/v1/workspaces/work/items", headers=H).status_code == 404
    assert api.post("/api/v1/workspaces/work/items", json={"title": "x"}, headers=H).status_code == 404
    assert api.get("/api/v1/items/2", headers=H).status_code == 404  # work の項目
    assert api.get("/api/v1/workspaces/ro/items", headers=H).status_code == 200
    r = api.post("/api/v1/workspaces/ro/items", json={"title": "x"}, headers=H)
    assert r.status_code == 403 and "read-only" in r.json()["detail"]
    assert api.post("/api/v1/items/1/notes", json={"body": "x"}, headers=H).status_code == 403
    assert api.post("/api/v1/items/1/move", json={"status": "doing"}, headers=H).status_code == 403
    assert api.get("/w/work").status_code == 200  # UI からは見える


def test_item_flow_with_source_rest(api: TestClient):
    r = api.post(
        "/api/v1/workspaces/blog/items",
        json={"title": "REST から ✓", "priority": "high", "tags": ["rest"], "links": [{"kind": "url", "target": "https://example.com"}]},
        headers=H,
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["created_by"] == "ai:gemini-analytics" and item["url"].endswith(f"/w/blog/items/{item['id']}")
    iid = item["id"]
    assert api.post(f"/api/v1/items/{iid}/move", json={"status": "candidate"}, headers=H).status_code == 409
    assert api.post(f"/api/v1/items/{iid}/move", json={"status": "doing", "reason": "go"}, headers=H).json()["status"] == "doing"
    r = api.patch(f"/api/v1/items/{iid}", json={"status": "done"}, headers=H)
    assert r.status_code == 400 and "move" in r.json()["detail"]
    r = api.patch(f"/api/v1/items/{iid}", json={"owner": "human", "due": "2026-12-31"}, headers=H)
    assert r.status_code == 200 and r.json()["owner"] == "human"
    assert api.patch(f"/api/v1/items/{iid}", json={"due": "bad"}, headers=H).status_code == 400
    assert api.patch(f"/api/v1/items/{iid}", json={"unknown": 1}, headers=H).status_code == 400
    assert api.patch(f"/api/v1/items/{iid}", json={}, headers=H).status_code == 400
    assert api.post(f"/api/v1/items/{iid}/notes", json={"body": "ノート"}, headers=H).status_code == 201
    r = api.post(f"/api/v1/items/{iid}/complete", json={"summary": "終了"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert api.post(f"/api/v1/items/{iid}/complete", json={}, headers=H).status_code == 409
    d = api.get(f"/api/v1/items/{iid}", headers=H).json()
    assert [n["body"] for n in d["notes"]] == ["ノート", "終了"]
    assert {e["source"] for e in d["events"]} == {"rest"} and {e["author"] for e in d["events"]} == {"ai:gemini-analytics"}
    lst = api.get("/api/v1/workspaces/blog/items?status=done&limit=1", headers=H).json()
    assert lst["total"] == 1 and "body" not in lst["items"][0]
    assert api.get("/api/v1/workspaces/blog/summary", headers=H).json()["counts"]["done"] == 1
    assert api.get("/api/v1/items/99999", headers=H).status_code == 404
    assert api.post("/api/v1/workspaces/blog/items", json={"title": ""}, headers=H).status_code == 400


def test_events_audit_hides_hidden_workspace(api: TestClient):
    api.post("/api/v1/workspaces/blog/items", json={"title": "e1"}, headers=H)
    evs = api.get("/api/v1/events?limit=100", headers=H).json()
    assert evs and all(e["kind"] for e in evs)
    # work（hidden）の item.created は含まれない: title で判定
    assert not any(e.get("payload", {}).get("title") == "仕事（hidden）" for e in evs)
    assert api.get("/api/v1/events?workspace=work", headers=H).status_code == 404
    blog = api.get("/api/v1/events?workspace=blog&limit=5", headers=H).json()
    assert blog[0]["kind"] == "item.created" and blog[0]["source"] == "rest"
    assert api.get("/api/v1/events?workspace=blog&limit=0", headers=H).status_code == 400


def test_docs_available(api: TestClient):
    assert api.get("/docs").status_code == 200
    paths = api.get("/openapi.json").json()["paths"]
    assert "/api/v1/workspaces/{slug}/items" in paths and "/api/v1/events" in paths
