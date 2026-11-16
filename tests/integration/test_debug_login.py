"""Development login (server.debug_mode): replaces ASF OAuth for local testing, localhost only."""

import urllib.parse

import pytest

from app.lib import config

PASSWORD = "test-pw"


@pytest.fixture
def debug_mode(monkeypatch):
    monkeypatch.setattr(config.server, "debug_mode", True)
    monkeypatch.setattr(config.server, "debug_password", PASSWORD)
    monkeypatch.setattr(config.server, "debug_user", "testuser")


async def log_in(post_form, **form):
    body = {"login": "/mailinglist-new.html", "uid": "testuser", "password": PASSWORD, "pmcs": "httpd, Tomcat"}
    body.update(form)
    return await post_form("/api/debug-login", {k: v for k, v in body.items() if v is not None})


async def session_of(client):
    resp = await client.get("/api/session")
    return await resp.get_json() if resp.status_code == 200 else None


# --- off by default ---------------------------------------------------------------


async def test_debug_login_is_off_without_debug_mode(client, post_form):
    assert (await client.get("/api/debug-login")).status_code == 404
    assert (await log_in(post_form)).status_code == 404
    assert await session_of(client) is None


async def test_oauth_login_goes_to_asf_oauth_without_debug_mode(client):
    resp = await client.get("/api/auth", query_string={"login": "/index.html"})
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("https://oauth.apache.org/")


# --- on: diverting /api/auth ------------------------------------------------------


@pytest.mark.parametrize(
    "query, expected_login",
    [("login=/matomo.html", "/matomo.html"), ("login", "/"), ("login=http%3A%2F%2Flocalhost%2Fx.html", "http://localhost/x.html")],
)
async def test_oauth_login_is_diverted_to_debug_form(client, debug_mode, query, expected_login):
    resp = await client.get(f"/api/auth?{query}")
    assert resp.status_code == 302
    location = urllib.parse.urlsplit(resp.headers["Location"])
    assert location.path == "/api/debug-login"
    assert urllib.parse.parse_qs(location.query) == {"login": [expected_login]}


async def test_other_oauth_requests_are_left_to_asfquart(client, debug_mode):
    resp = await client.get("/api/auth")
    assert resp.status_code == 404  # no session yet, as asfquart answers
    resp = await client.get("/api/auth", query_string={"logout": "/"})
    assert resp.status_code == 302 and resp.headers["Location"] == "/"


async def test_form_is_shown_with_escaped_values(client, debug_mode):
    resp = await client.get("/api/debug-login", query_string={"login": '/x"><script>alert(1)</script>'})
    assert resp.status_code == 200
    page = await resp.get_data(as_text=True)
    assert 'value="testuser"' in page
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
    assert "Never" in page or "never" in page  # the production warning


# --- on: logging in ---------------------------------------------------------------


async def test_login_creates_the_chosen_session(client, post_form, debug_mode):
    resp = await log_in(post_form, root="1")
    assert resp.status_code == 200
    assert resp.headers["Refresh"] == "0; url=/mailinglist-new.html"
    data = await session_of(client)
    assert data["uid"] == "testuser"
    assert data["pmcs"] == ["httpd", "tomcat"]  # trimmed, lowercased, sorted
    assert data["projects"] == ["httpd", "tomcat"]
    assert data["root"] is True


async def test_logged_in_user_can_use_protected_endpoints(client, post_form, debug_mode):
    assert (await client.get("/api/jira-project-schemes")).status_code == 302  # login redirect
    await log_in(post_form)
    assert (await client.get("/api/jira-project-schemes")).status_code == 200


async def test_plain_pmc_member_is_not_root(client, post_form, debug_mode):
    await log_in(post_form, uid="bob", pmcs="httpd")
    data = await session_of(client)
    assert (data["uid"], data["pmcs"], data["root"]) == ("bob", ["httpd"], False)


@pytest.mark.parametrize(
    "login, target",
    [
        ("/matomo.html?project=httpd", "/matomo.html?project=httpd"),
        ("http://localhost/matomo.html?project=httpd", "/matomo.html?project=httpd"),  # same site, as the JS sends it
        ("https://evil.example/", "/"),
        ("//evil.example/", "/"),
        ("javascript:alert(1)", "/"),
        ("http://localhost.evil.example/", "/"),
        ("relative.html", "/"),
        ("/\\evil.example", "/"),
    ],
)
async def test_redirect_after_login_stays_on_this_site(client, post_form, debug_mode, login, target):
    resp = await log_in(post_form, login=login)
    assert resp.headers["Refresh"] == f"0; url={target}"


@pytest.mark.parametrize(
    "form, status, message",
    [
        ({"password": "wrong"}, 403, "Wrong debug password"),
        ({"password": None}, 403, "Wrong debug password"),
        ({"uid": "Not A Uid!"}, 400, "valid user ID"),
        ({"uid": ""}, 400, "valid user ID"),
        ({"pmcs": "httpd, bad/name"}, 400, "Invalid project name(s): bad/name"),
    ],
)
async def test_login_rejections(client, post_form, debug_mode, form, status, message):
    resp = await log_in(post_form, **form)
    assert resp.status_code == status
    assert message in await resp.get_data(as_text=True)
    assert await session_of(client) is None


async def test_debug_login_refuses_public_hostnames(client, post_form, debug_mode):
    """Defence in depth: even with debug mode on by mistake, a public hostname gets no dev login."""
    host = {"Host": "selfserve.apache.org"}
    assert (await client.get("/api/debug-login", headers=host)).status_code == 404
    assert (await post_form("/api/debug-login", {"uid": "x", "password": PASSWORD}, headers=host)).status_code == 404
    resp = await client.get("/api/auth", query_string={"login": "/"}, headers=host)
    assert resp.headers["Location"].startswith("https://oauth.apache.org/")


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
async def test_debug_login_accepts_local_hostnames(client, debug_mode, host):
    assert (await client.get("/api/debug-login", headers={"Host": host})).status_code == 200
