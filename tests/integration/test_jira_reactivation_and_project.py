"""Jira account reactivation (email-confirmed, via ACLI) and Jira project creation."""

import pytest

from app.endpoints import jira_activate_account as reactivation

# --- reactivation --------------------------------------------------------------


@pytest.fixture
def known_account(monkeypatch):
    monkeypatch.setattr(reactivation, "JIRA_EMAIL_MAPPINGS", {"olduser": "Old.User@example.org"})
    monkeypatch.setattr(reactivation, "JIRA_REACTIVATION_QUEUE", {})


async def request_reactivation(client, username="olduser", email="old.user@example.org"):
    resp = await client.post("/api/jira-account-activate", json={"username": username, "email": email})
    return await resp.get_json()


async def test_reactivation_sends_confirmation_for_matching_email(client, known_account, sent_mail):
    assert await request_reactivation(client) == {"success": True}  # email match is case-insensitive
    ((token, username),) = reactivation.JIRA_REACTIVATION_QUEUE.items()
    assert username == "olduser"
    (mail,) = sent_mail
    assert mail["recipient"] == "old.user@example.org"
    assert f"jira-account-reactivate.html?{token}" in mail["message"]


@pytest.mark.parametrize(
    "username, email, message",
    [
        ("olduser", "someone@apache.org", "internal ASF accounts"),
        ("olduser", "wrong@example.org", "unable to find the account"),
        ("nobody", "old.user@example.org", "unable to find the account"),
    ],
)
async def test_reactivation_rejections(client, known_account, sent_mail, username, email, message):
    data = await request_reactivation(client, username, email)
    assert data["success"] is False and message in data["message"]
    assert not reactivation.JIRA_REACTIVATION_QUEUE
    assert not sent_mail


async def confirm(client):
    ((token, _),) = reactivation.JIRA_REACTIVATION_QUEUE.items()
    resp = await client.post("/api/jira-account-activate-confirm", json={"token": token})
    return await resp.get_json()


async def test_confirmation_reactivates_via_acli(client, known_account, acli):
    await request_reactivation(client)
    assert await confirm(client) == {"success": True, "activated": True}
    (argv,) = acli.calls
    assert argv[0] == reactivation.ACLI_CMD
    assert "--activate" in argv
    assert argv[argv.index("--userEmail") + 1] == "Old.User@example.org"
    assert not reactivation.JIRA_REACTIVATION_QUEUE  # token is single-use


async def test_confirmation_tolerates_acli_complaining_after_success(client, known_account, acli):
    """Regression: ACLI output is bytes; checking it for '"active":true' used to raise TypeError."""
    await request_reactivation(client)
    acli.respond = lambda argv: (1, b'{"name":"olduser","active":true}', b"warning: email redacted")
    assert await confirm(client) == {"success": True, "activated": True}


async def test_confirmation_reports_acli_failure(client, known_account, acli):
    await request_reactivation(client)
    acli.respond = lambda argv: (1, b"", b"error")
    data = await confirm(client)
    assert data["activated"] is False and "internal server error" in data["error"]


async def test_confirmation_rejects_unknown_token(client, known_account):
    resp = await client.post("/api/jira-account-activate-confirm", json={"token": "nope"})
    assert (await resp.get_json())["success"] is False


# --- project creation ------------------------------------------------------------


def project_form(**overrides):
    body = {
        "project_key": "HTTPDX",
        "project_name": "HTTPD Extras",
        "description": "Issue tracker for httpd extras",
        "project_lead": "bob",
        "ldap_project": "httpd",
        "issue_scheme": "Default",
        "workflow_scheme": "Default",
        "homepage_url": "https://httpd.apache.org/",
    }
    body.update(overrides)
    return body


async def create_project(client, headers, **overrides):
    resp = await client.post("/api/jira-project-create", json=project_form(**overrides), headers=headers)
    return await resp.get_json()


async def test_pmc_member_creates_project(client, auth, acli, sent_mail):
    assert (await create_project(client, auth("pmc")))["success"] is True
    actions = [argv[argv.index("--action") + 1] for argv in acli.calls]
    assert actions == ["getUser", "createProject", "addProjectRoleActors", "addProjectRoleActors"]
    groups = [argv[argv.index("--group") + 1] for argv in acli.calls[2:]]
    assert groups == ["httpd-pmc", "httpd"]
    (mail,) = sent_mail
    assert mail["recipient"] == ("private@infra.apache.org", "private@httpd.apache.org", "bob@apache.org")


@pytest.mark.parametrize(
    "persona, overrides, message",
    [
        ("committer", {}, "Only members of a (P)PMC"),
        ("pmc", {"project_key": "bad key"}, "Invalid project key"),
        ("pmc", {"ldap_project": "nonexistent"}, "valid, current apache project"),
        ("other-pmc", {}, "you are on the PMC of"),
        ("pmc", {"homepage_url": ""}, "homepage URL"),
    ],
)
async def test_project_creation_rejections(client, auth, acli, sent_mail, persona, overrides, message):
    data = await create_project(client, auth(persona), **overrides)
    assert data["success"] is False and message in data["message"]
    assert not acli.calls
    assert not sent_mail


async def test_project_creation_stops_when_lead_unknown(client, auth, acli):
    acli.respond = lambda argv: (1, b"", b"") if "getUser" in argv else (0, b"", b"")
    data = await create_project(client, auth("pmc"))
    assert "project lead ID" in data["message"]
    assert len(acli.calls) == 1


async def test_root_can_create_for_any_project(client, auth, acli):
    assert (await create_project(client, auth("root"), ldap_project="tomcat"))["success"] is True
