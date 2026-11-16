"""Inventory of every /api route and who may call it.

A new endpoint fails this test until it is listed here, which makes "is this meant to
be reachable without logging in?" an explicit decision instead of a missing decorator.
"""

import pytest

# Reachable without a session: public data, self-service account requests (each step is
# confirmed by email), and asfquart's own OAuth endpoint.
PUBLIC = {
    "/api/auth",
    "/api/public",
    "/api/session",
    "/api/jira-exists",
    "/api/jira-project-blocked",
    "/api/jira-account",
    "/api/jira-account-activate",
    "/api/jira-account-activate-confirm",
    "/api/confluence-exists",
    "/api/confluence-project-blocked",
    "/api/confluence-account",
    "/api/confluence-account-activate",
    "/api/confluence-account-activate-confirm",
}

# Need a session; maps each route to a method it accepts.
PROTECTED = {
    "/api/jira-account-review": "GET",
    "/api/jira-project-create": "POST",
    "/api/jira-project-schemes": "GET",
    "/api/confluence-account-review": "GET",
    "/api/confluence-archive": "POST",
    "/api/confluence-create": "POST",
    "/api/mailinglist": "POST",
    "/api/queue": "GET",
}


def test_every_api_route_is_classified(application):
    routes = {rule.rule for rule in application.url_map.iter_rules() if rule.rule.startswith("/api/")}
    assert routes == PUBLIC | set(PROTECTED)


@pytest.mark.parametrize("path", PROTECTED)
async def test_protected_routes_send_anonymous_callers_to_login(client, acli, sent_mail, path):
    resp = await client.open(path, method=PROTECTED[path])
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/api/auth?login=")
    assert not acli.calls
    assert not sent_mail


@pytest.mark.parametrize("path", PROTECTED)
async def test_protected_routes_refuse_unknown_tokens(client, acli, sent_mail, path):
    resp = await client.open(path, method=PROTECTED[path], headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code in (401, 403)
    assert not acli.calls
    assert not sent_mail
