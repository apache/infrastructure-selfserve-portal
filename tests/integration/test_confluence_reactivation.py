"""Confluence account reactivation (email-confirmed, via ACLI). Mirrors the Jira flow, separate code."""

import pytest

from app.endpoints import confluence_activate_account as reactivation


@pytest.fixture
def known_account(monkeypatch):
    monkeypatch.setattr(reactivation, "CONFLUENCE_EMAIL_MAPPINGS", {"olduser": "Old.User@example.org"})
    monkeypatch.setattr(reactivation, "CONFLUENCE_REACTIVATION_QUEUE", {})


async def request_reactivation(client, username="olduser", email="old.user@example.org"):
    resp = await client.post("/api/confluence-account-activate", json={"username": username, "email": email})
    return await resp.get_json()


async def confirm(client):
    ((token, _),) = reactivation.CONFLUENCE_REACTIVATION_QUEUE.items()
    resp = await client.post("/api/confluence-account-activate-confirm", json={"token": token})
    return await resp.get_json()


async def test_reactivation_sends_confirmation_for_matching_email(client, known_account, sent_mail):
    assert await request_reactivation(client) == {"success": True}  # email match is case-insensitive
    ((token, username),) = reactivation.CONFLUENCE_REACTIVATION_QUEUE.items()
    assert username == "olduser"
    (mail,) = sent_mail
    assert mail["recipient"] == "old.user@example.org"
    assert f"confluence-account-reactivate.html?{token}" in mail["message"]


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
    assert not reactivation.CONFLUENCE_REACTIVATION_QUEUE
    assert not sent_mail


async def test_confirmation_reactivates_via_acli(client, known_account, acli):
    await request_reactivation(client)
    assert await confirm(client) == {"success": True, "activated": True}
    (argv,) = acli.calls
    assert argv[:2] == (reactivation.ACLI_CMD, "confluence")
    assert "--activate" in argv
    assert argv[argv.index("--userId") + 1] == "olduser"
    assert argv[argv.index("--userEmail") + 1] == "Old.User@example.org"
    assert not reactivation.CONFLUENCE_REACTIVATION_QUEUE  # token is single-use


async def test_confirmation_tolerates_acli_complaining_after_success(client, known_account, acli):
    """Regression: ACLI output is bytes; checking it for '"active":true' used to raise TypeError."""
    await request_reactivation(client)
    acli.respond = lambda argv: (1, b"", b'warning: email redacted {"name":"olduser","active":true}')
    assert await confirm(client) == {"success": True, "activated": True}


async def test_confirmation_reports_acli_failure(client, known_account, acli):
    await request_reactivation(client)
    acli.respond = lambda argv: (1, b"", b"error")
    data = await confirm(client)
    assert data["activated"] is False and "internal server error" in data["error"]


async def test_confirmation_rejects_unknown_token(client, known_account, acli):
    resp = await client.post("/api/confluence-account-activate-confirm", json={"token": "nope"})
    assert (await resp.get_json())["success"] is False
    assert not acli.calls


@pytest.mark.parametrize("body", [{"username": "olduser"}, {"email": "old.user@example.org"}, {}])
async def test_reactivation_needs_username_and_email(client, known_account, sent_mail, body):
    """Regression: a missing field used to be a 500."""
    resp = await client.post("/api/confluence-account-activate", json=body)
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["success"] is False and "provide both" in data["message"]
    assert not sent_mail


async def test_confirmation_fails_cleanly_when_account_has_gone(client, known_account, acli):
    """Regression: used to be a 500 if the account left the email map between request and confirmation."""
    await request_reactivation(client)
    reactivation.CONFLUENCE_EMAIL_MAPPINGS.clear()
    data = await confirm(client)
    assert data["success"] is False and data["activated"] is False
    assert "no longer be found" in data["error"]
    assert not acli.calls
    assert not reactivation.CONFLUENCE_REACTIVATION_QUEUE
