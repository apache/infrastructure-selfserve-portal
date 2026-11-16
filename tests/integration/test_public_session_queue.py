"""Public data, session info, and the role-account request queue."""

import json
import os

import pytest

from app.lib import config


async def test_public_feed_lists_projects_and_mail_domains(client):
    resp = await client.get("/api/public")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["projects"] == ["httpd", "infra", "tomcat", "tooling"]
    assert data["mail_domains"]["httpd"] == "httpd.apache.org"


async def test_session_reports_the_authenticated_user(client, auth):
    resp = await client.get("/api/session", headers=auth("pmc"))
    data = await resp.get_json()
    assert data["uid"] == "bob"
    assert data["pmcs"] == ["httpd"]
    assert data["root"] is False
    assert data["roleaccount"] is False
    assert data["all_projects"] == config.projects


async def test_session_without_login_is_not_found(client):
    """Regression: used to be a 500. 404 is what asfquart's own /api/auth answers when logged out."""
    resp = await client.get("/api/session")
    assert resp.status_code == 404
    assert (await resp.get_json())["success"] is False


async def test_session_logout(client, auth):
    resp = await client.get("/api/session", query_string={"action": "logout"}, headers=auth("pmc"))
    assert await resp.get_data(as_text=True) == "Logged out!"


def _queue(name: str, payload: dict) -> str:
    path = os.path.join(config.storage.queue_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


async def test_queue_requires_role_account_or_root(client, auth):
    unauthenticated = await client.get("/api/queue")
    assert unauthenticated.status_code == 302  # sent to OAuth login
    for persona in ("committer", "pmc", "member"):
        resp = await client.get("/api/queue", headers=auth(persona))
        assert resp.status_code == 403, persona


async def test_queue_lists_pending_requests(client, auth):
    _queue("mailinglist-dev-httpd.apache.org.json", {"id": "a"})
    _queue("mailinglist-users-httpd.apache.org.json", {"id": "b"})
    with open(os.path.join(config.storage.queue_dir, "broken.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    for persona in ("role", "root"):
        resp = await client.get("/api/queue", headers=auth(persona))
        assert resp.status_code == 200
        assert sorted(item["id"] for item in await resp.get_json()) == ["a", "b"]  # broken file skipped


async def test_queue_item_removal(client, auth):
    path = _queue("mailinglist-dev-httpd.apache.org.json", {"id": "a"})
    resp = await client.get("/api/queue", query_string={"rm": os.path.basename(path)}, headers=auth("role"))
    assert (await resp.get_json())["success"] is True
    assert not os.path.exists(path)

    again = await client.get("/api/queue", query_string={"rm": os.path.basename(path)}, headers=auth("role"))
    assert again.status_code == 404


async def test_queue_removal_rejects_path_traversal(client, auth, tmp_path):
    outside = tmp_path / "victim.json"
    outside.write_text("{}")
    rel = os.path.relpath(outside, config.storage.queue_dir)
    resp = await client.get("/api/queue", query_string={"rm": rel}, headers=auth("role"))
    assert resp.status_code == 400
    assert outside.exists()


@pytest.mark.parametrize("name", ["../x.json", "Mailinglist-Dev.json", "mailinglist-dev.txt", "a b.json", ".json/"])
async def test_queue_removal_rejects_invalid_names(client, auth, name):
    """Regression: used to be a 500 from a bare assert."""
    resp = await client.get("/api/queue", query_string={"rm": name}, headers=auth("role"))
    assert resp.status_code == 400
    assert await resp.get_json() == {"success": False, "message": "Invalid queue item name"}
