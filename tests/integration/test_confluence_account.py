"""Confluence account lifecycle. Same shape as the Jira flow, but separate code (and tables)."""

import pytest

from app.endpoints import confluenceaccount

INFRAREPORTS = confluenceaccount.INFRAREPORTS_USERID_CHECK
DB = confluenceaccount.CONFLUENCE_DB


def application_form(**overrides):
    body = {
        "username": "wikiuser",
        "realname": "Wiki User",
        "email": "wiki.user@example.org",
        "project": "httpd",
        "why": "I want to help improve the httpd wiki docs.",
    }
    body.update(overrides)
    return body


@pytest.fixture
def submit(post_form):
    async def send(**overrides):
        resp = await post_form("/api/confluence-account", application_form(**overrides))
        return await resp.get_json()

    return send


@pytest.fixture
def submit_and_verify(client, submit):
    async def run():
        assert (await submit())["success"] is True
        token = DB.fetchone("cwiki_pending", userid="wikiuser")["token"]
        resp = await client.get("/api/confluence-account", query_string={"token": token})
        assert (await resp.get_json())["success"] is True
        return token

    return run


async def test_exists_checks_local_db_then_infra_reports(client, http):
    DB.insert("cwiki_users", {"userid": "taken"})
    resp = await client.get("/api/confluence-exists", query_string={"userid": "taken"})
    assert await resp.get_json() == {"found": True}

    http.routes[INFRAREPORTS] = (200, {"exists": False})
    resp = await client.get("/api/confluence-exists", query_string={"userid": "free"})
    assert await resp.get_json() == {"found": False}

    http.routes[INFRAREPORTS] = (500, {})
    resp = await client.get("/api/confluence-exists", query_string={"userid": "free"})
    assert (await resp.get_json())["success"] is False


async def test_project_blocked(client):
    DB.insert("cwiki_blocked", {"project": "tomcat"})
    for project, blocked in (("tomcat", True), ("httpd", False)):
        resp = await client.post("/api/confluence-project-blocked", json={"project": project})
        assert await resp.get_json() == {"blocked": blocked}


async def test_request_and_verification(client, sent_mail, submit_and_verify):
    token = await submit_and_verify()
    verify_mail, review_mail = sent_mail
    assert verify_mail["recipient"] == "wiki.user@example.org"
    assert f"confluence-account-verify.html?{token}" in verify_mail["message"]
    assert review_mail["recipient"] == [confluenceaccount.NOTIFICATION_TARGET, "private@httpd.apache.org"]
    assert DB.fetchone("cwiki_pending", token=token)["validated"] == 1

    again = await client.get("/api/confluence-account", query_string={"token": token})
    assert (await again.get_json())["success"] is False


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"username": "abc"}, "at least be four character"),
        ({"realname": "Al"}, "at least three characters"),
        ({"email": "nope"}, "valid email address"),
        ({"project": "not-a-project"}, "valid project"),
        ({"why": "short"}, "valid reason"),
    ],
)
async def test_request_validation(sent_mail, submit, overrides, message):
    data = await submit(**overrides)
    assert data["success"] is False and message in data["message"]
    assert not sent_mail


async def test_request_rejects_blocked_project_and_duplicates(submit):
    DB.insert("cwiki_blocked", {"project": "tomcat"})
    assert "does not use Confluence" in (await submit(project="tomcat"))["message"]
    assert (await submit())["success"] is True
    assert "already in use" in (await submit(email="x@example.org"))["message"]
    assert "already a pending" in (await submit(username="otheruser"))["message"]


async def test_review_is_limited_to_project_committers(client, auth, submit_and_verify):
    token = await submit_and_verify()
    denied = await client.get("/api/confluence-account-review", query_string={"token": token}, headers=auth("other-pmc"))
    assert (await denied.get_json())["success"] is False
    allowed = await client.get("/api/confluence-account-review", query_string={"token": token}, headers=auth("committer"))
    assert (await allowed.get_json())["entry"]["userid"] == "wikiuser"


async def test_approve_creates_account(auth, acli, sent_mail, submit_and_verify, post_form):
    token = await submit_and_verify()
    sent_mail.clear()
    resp = await post_form("/api/confluence-account-review", {"token": token, "action": "approve"}, auth("committer"))
    assert (await resp.get_json())["success"] is True
    (argv,) = acli.calls
    assert argv[0] == "/opt/confluence-cli/acli.sh"
    assert "wikiuser" in argv
    assert DB.fetchone("cwiki_pending", token=token) is None
    assert DB.fetchone("cwiki_users", userid="wikiuser") is not None
    assert len(sent_mail) == 2


async def test_approve_reports_acli_failure(auth, acli, submit_and_verify, post_form):
    token = await submit_and_verify()
    acli.respond = lambda argv: (1, b"", b"A user with that username already exists")
    resp = await post_form("/api/confluence-account-review", {"token": token, "action": "approve"}, auth("committer"))
    assert "already exists in Confluence" in (await resp.get_json())["message"]
    assert DB.fetchone("cwiki_users", userid="wikiuser") is None


async def test_deny_marks_request_and_notifies(auth, sent_mail, submit_and_verify, post_form):
    # Unlike Jira, a second deny is not refused (and re-sends both emails); not asserted here.
    token = await submit_and_verify()
    sent_mail.clear()
    form = {"token": token, "action": "deny", "reason": "Wiki is read-only."}
    resp = await post_form("/api/confluence-account-review", form, auth("committer"))
    assert (await resp.get_json())["success"] is True
    assert DB.fetchone("cwiki_pending", token=token)["denied_ts"] > 0
    assert [m["recipient"] for m in sent_mail] == [
        "wiki.user@example.org",
        [confluenceaccount.NOTIFICATION_TARGET, "private@httpd.apache.org"],
    ]
    assert "Wiki is read-only." in sent_mail[0]["message"]


async def test_review_rejects_unknown_action(auth, acli, sent_mail, submit_and_verify, post_form):
    """Regression: anything but approve/deny used to be a 500."""
    token = await submit_and_verify()
    sent_mail.clear()
    resp = await post_form("/api/confluence-account-review", {"token": token, "action": "delete"}, auth("committer"))
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["success"] is False and "Invalid action" in data["message"]
    assert DB.fetchone("cwiki_pending", token=token)["denied_ts"] == 0  # request untouched
    assert not acli.calls
    assert not sent_mail
