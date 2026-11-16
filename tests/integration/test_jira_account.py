"""Jira account lifecycle: lookup helpers, request, email verification, PMC review."""

import pytest

from app.endpoints import jiraaccount

INFRAREPORTS = jiraaccount.INFRAREPORTS_USERID_CHECK
DB = jiraaccount.JIRA_DB


def application_form(**overrides):
    body = {
        "username": "newuser",
        "realname": "New User",
        "email": "new.user@example.org",
        "project": "httpd",
        "why": "I would like to report a bug in mod_ssl.",
    }
    body.update(overrides)
    return body


@pytest.fixture
def username_free(http):
    http.routes[INFRAREPORTS] = (200, {"exists": False})
    return http


@pytest.fixture
def submit(post_form):
    async def send(**overrides):
        resp = await post_form("/api/jira-account", application_form(**overrides))
        return await resp.get_json()

    return send


@pytest.fixture
def submit_and_verify(client, submit):
    async def run():
        assert (await submit())["success"] is True
        token = DB.fetchone("pending", userid="newuser")["token"]
        resp = await client.get("/api/jira-account", query_string={"token": token})
        assert (await resp.get_json())["success"] is True
        return token

    return run


# --- lookups -----------------------------------------------------------------

async def test_exists_checks_local_db_first(client, http):
    DB.insert("users", {"userid": "taken"})
    resp = await client.get("/api/jira-exists", query_string={"userid": "taken"})
    assert await resp.get_json() == {"found": True}
    assert not http.requests


@pytest.mark.parametrize("remote, expected", [({"exists": True}, True), ({"exists": False}, False), ({}, True)])
async def test_exists_falls_back_to_infra_reports(client, http, remote, expected):
    http.routes[INFRAREPORTS] = (200, remote)
    resp = await client.get("/api/jira-exists", query_string={"userid": "someone"})
    assert await resp.get_json() == {"found": expected}
    assert http.requests == [(INFRAREPORTS, {"id": "someone"})]


async def test_exists_reports_backend_failure(client, http):
    http.routes[INFRAREPORTS] = (503, {})
    resp = await client.get("/api/jira-exists", query_string={"userid": "someone"})
    assert (await resp.get_json())["success"] is False


async def test_project_blocked(client):
    DB.insert("blocked", {"project": "tomcat"})
    for project, blocked in (("tomcat", True), ("httpd", False)):
        resp = await client.post("/api/jira-project-blocked", json={"project": project})
        assert await resp.get_json() == {"blocked": blocked}


# --- request + verification --------------------------------------------------

async def test_request_creates_pending_entry_and_sends_verification(client, username_free, sent_mail, submit):
    data = await submit()
    assert data == {"success": True, "message": "Request logged. Please verify your email address"}

    entry = DB.fetchone("pending", userid="newuser")
    assert entry["validated"] == 0
    assert entry["email"] == "new.user@example.org"
    (mail,) = sent_mail
    assert mail["recipient"] == "new.user@example.org"
    assert f"jira-account-verify.html?{entry['token']}" in mail["message"]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"username": "abc"}, "at least be four character"),
        ({"username": "Bad-Name"}, "Invalid Jira user name"),
        ({"realname": "Al"}, "at least three characters"),
        ({"email": "nope"}, "valid email address"),
        ({"project": "not-a-project"}, "valid project"),
        ({"why": "short"}, "valid reason"),
    ],
)
async def test_request_validation(client, username_free, sent_mail, overrides, message, submit):
    data = await submit(**overrides)
    assert data["success"] is False and message in data["message"]
    assert DB.fetchone("pending", userid=overrides.get("username", "newuser")) is None
    assert not sent_mail


async def test_request_rejected_for_blocked_project(client, username_free, submit):
    DB.insert("blocked", {"project": "httpd"})
    assert "does not use Jira" in (await submit())["message"]


async def test_request_rejects_taken_or_pending_usernames(client, username_free, submit):
    DB.insert("users", {"userid": "newuser"})
    assert "already in use" in (await submit())["message"]
    DB.delete("users", userid="newuser")

    assert (await submit())["success"] is True
    again = await submit(email="other@example.org")
    assert "already in use" in again["message"]
    same_email = await submit(username="seconduser")
    assert "already a pending" in same_email["message"]


async def test_request_rejects_username_known_to_infra_reports(client, http, submit):
    http.routes[INFRAREPORTS] = (200, {"exists": True})
    assert "already in use" in (await submit())["message"]


async def test_verification_notifies_project_once(client, username_free, sent_mail, submit_and_verify):
    token = await submit_and_verify()
    assert DB.fetchone("pending", token=token)["validated"] == 1
    review_mail = sent_mail[-1]
    assert review_mail["recipient"] == [jiraaccount.NOTIFICATION_TARGET, "private@httpd.apache.org"]
    assert f"jira-account-review.html?token={token}" in review_mail["message"]

    again = await client.get("/api/jira-account", query_string={"token": token})
    assert (await again.get_json())["success"] is False


# --- review --------------------------------------------------------------------

async def test_review_requires_login_and_project_membership(client, username_free, auth, submit_and_verify):
    token = await submit_and_verify()
    assert (await client.get("/api/jira-account-review", query_string={"token": token})).status_code == 302
    resp = await client.get("/api/jira-account-review", query_string={"token": token}, headers=auth("other-pmc"))
    data = await resp.get_json()
    assert data["success"] is False and "projects you are on" in data["message"]


async def test_review_rejects_unverified_and_unknown_tokens(client, username_free, auth, submit):
    assert (await submit())["success"] is True
    token = DB.fetchone("pending", userid="newuser")["token"]
    resp = await client.get("/api/jira-account-review", query_string={"token": token}, headers=auth("committer"))
    assert "not been verified" in (await resp.get_json())["message"]

    for bad in ("short", "00000000-0000-0000-0000-000000000000"):
        resp = await client.get("/api/jira-account-review", query_string={"token": bad}, headers=auth("committer"))
        assert (await resp.get_json())["success"] is False


async def test_review_shows_request_without_private_fields(client, username_free, auth, submit_and_verify):
    token = await submit_and_verify()
    for persona in ("committer", "root"):
        resp = await client.get("/api/jira-account-review", query_string={"token": token}, headers=auth(persona))
        entry = (await resp.get_json())["entry"]
        assert set(entry) == {"created", "project", "userid", "realname", "userip", "why"}


async def test_approve_creates_account(client, username_free, auth, acli, sent_mail, submit_and_verify, post_form):
    token = await submit_and_verify()
    sent_mail.clear()
    resp = await post_form(
        "/api/jira-account-review", {"token": token, "action": "approve"}, auth("committer")
    )
    assert (await resp.get_json())["success"] is True

    (argv,) = acli.calls
    assert argv[0] == "/opt/jira-cli/acli.sh"
    assert argv[argv.index("--userId") + 1] == "newuser"
    assert argv[argv.index("--userEmail") + 1] == "new.user@example.org"
    assert DB.fetchone("pending", token=token) is None
    assert DB.fetchone("users", userid="newuser") is not None
    assert [m["recipient"] for m in sent_mail] == [
        "new.user@example.org",
        [jiraaccount.NOTIFICATION_TARGET, "private@httpd.apache.org"],
    ]


@pytest.mark.parametrize(
    "result, message",
    [
        ((1, b"", b"A user with that username already exists"), "already exists in Jira"),
        ((1, b"", b"Client error: User 'newuser' is already defined."), "naming conflict"),
        ((1, b"", b"boom"), "internal server error"),
    ],
)
async def test_approve_reports_acli_failures(client, username_free, auth, acli, result, message, submit_and_verify, post_form):
    token = await submit_and_verify()
    acli.respond = lambda argv: result
    resp = await post_form(
        "/api/jira-account-review", {"token": token, "action": "approve"}, auth("committer")
    )
    data = await resp.get_json()
    assert data["success"] is False and message in data["message"]
    assert DB.fetchone("pending", token=token) is not None  # left for another attempt
    assert DB.fetchone("users", userid="newuser") is None


async def test_deny_notifies_once(client, username_free, auth, sent_mail, submit_and_verify, post_form):
    token = await submit_and_verify()
    sent_mail.clear()
    form = {"token": token, "action": "deny", "reason": "Please use the mailing list."}
    resp = await post_form("/api/jira-account-review", form, auth("committer"))
    assert (await resp.get_json())["success"] is True
    assert DB.fetchone("pending", token=token)["denied_ts"] > 0
    assert "Please use the mailing list." in sent_mail[0]["message"]
    assert len(sent_mail) == 2

    again = await post_form("/api/jira-account-review", form, auth("committer"))
    assert "already been denied" in (await again.get_json())["message"]
