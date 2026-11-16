"""Matomo property creation: validation, the Matomo API calls, and who gets told."""

import asyncio
import urllib.parse

import aiohttp
import pytest

from app.endpoints import matomo
from app.lib import config

MATOMO_URL = "https://analytics.example.org/"
TOKEN = "s3cr3t-token"


class FakeMatomoResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self, content_type="application/json"):  # pylint: disable=unused-argument
        return self._payload

    async def text(self):
        return str(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakeMatomo:
    """A tiny Matomo: tracks sites by URL and answers the API methods the portal uses.

    `calls` holds (url, form data) per request. Set `override[method]` to (status, payload)
    or to an exception instance to make that method fail.
    """

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.sites: dict[str, int] = {}
        self.override: dict = {}
        self.next_id = 41

    @staticmethod
    def key(url):
        # Matomo matches regardless of scheme and www.
        parsed = urllib.parse.urlsplit(url)
        return parsed.hostname.removeprefix("www.") + parsed.path.rstrip("/")

    def methods(self):
        return [data["method"] for _url, data in self.calls]

    def answer(self, data):
        method = data["method"]
        if method in self.override:
            result = self.override[method]
            if isinstance(result, Exception):
                raise result
            return result
        if method == "SitesManager.getSitesIdFromSiteUrl":
            site_id = self.sites.get(self.key(data["url"]))
            return 200, [{"idsite": str(site_id)}] if site_id else []
        if method == "SitesManager.addSite":
            self.next_id += 1
            self.sites[self.key(data["urls[]"])] = self.next_id
            return 200, {"value": self.next_id}
        if method == "UsersManager.setUserAccess":
            return 200, {"result": "success", "message": "ok"}
        if method == "SitesManager.getJavascriptTag":
            return 200, {"value": f'<!-- Matomo -->\n<script>_paq.push(["setSiteId", "{data["idSite"]}"]);</script>'}
        return 200, {"result": "error", "message": f"unknown method {method}"}

    def session(self, *_args, **_kwargs):
        fake = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            def post(self, url, data=None, **_kwargs):
                fake.calls.append((url, dict(data)))
                return FakeMatomoResponse(*fake.answer(data))

        return Session()


@pytest.fixture
def matomo_api(monkeypatch):
    fake = FakeMatomo()
    monkeypatch.setattr(aiohttp, "ClientSession", fake.session)
    monkeypatch.setattr(config.matomo, "url", MATOMO_URL)
    monkeypatch.setattr(config.matomo, "token", TOKEN)
    monkeypatch.setattr(config.matomo, "anonymous_view", True)
    monkeypatch.setattr(config, "committee_names", {"httpd": "HTTP Server", "tomcat": "Tomcat"})
    return fake


async def request_site(post_form, headers, **form):
    body = {"project": "httpd", "url": "https://httpd.apache.org/"}
    body.update(form)
    resp = await post_form("/api/matomo-site-create", {k: v for k, v in body.items() if v is not None}, headers=headers)
    assert resp.status_code == 200
    return await resp.get_json()


async def test_pmc_member_creates_main_site(post_form, auth, matomo_api, sent_mail):
    data = await request_site(post_form, auth("pmc"))
    assert data["success"] is True
    assert data["site_id"] == 42
    assert data["site_name"] == "Apache HTTP Server"
    assert data["site_url"] == "https://httpd.apache.org"
    assert '"setSiteId", "42"' in data["tracking_code"]
    assert data["dashboard_url"].startswith(f"{MATOMO_URL}index.php?") and "idSite=42" in data["dashboard_url"]
    assert "private@httpd.apache.org" in data["message"]

    assert matomo_api.methods() == [
        "SitesManager.getSitesIdFromSiteUrl",
        "SitesManager.addSite",
        "UsersManager.setUserAccess",
        "SitesManager.getJavascriptTag",
    ]
    for url, form in matomo_api.calls:
        assert url == f"{MATOMO_URL}index.php"
        assert form["token_auth"] == TOKEN and form["format"] == "JSON" and form["module"] == "API"
    add_site = matomo_api.calls[1][1]
    assert (add_site["siteName"], add_site["urls[]"]) == ("Apache HTTP Server", "https://httpd.apache.org")
    access = matomo_api.calls[2][1]
    assert (access["userLogin"], access["access"], access["idSites"]) == ("anonymous", "view", 42)

    (mail,) = sent_mail
    assert mail["recipient"] == ("private@infra.apache.org", "private@httpd.apache.org", "bob@apache.org")
    assert mail["subject"] == "Matomo property created: Apache HTTP Server"
    assert "Site ID:  42" in mail["message"]
    assert '"setSiteId", "42"' in mail["message"]


@pytest.mark.parametrize("url", ["https://www.httpd.apache.org", "HTTPS://HTTPD.apache.org//"])
async def test_main_site_variants_need_no_label(post_form, auth, matomo_api, url):
    data = await request_site(post_form, auth("pmc"), url=url)
    assert data["success"] is True and data["site_name"] == "Apache HTTP Server"


@pytest.mark.parametrize(
    "url, expected_url",
    [
        ("https://httpd.apache.org/docs/", "https://httpd.apache.org/docs"),
        ("https://wiki.httpd.apache.org", "https://wiki.httpd.apache.org"),
    ],
)
async def test_additional_site_gets_labelled_name(post_form, auth, matomo_api, sent_mail, url, expected_url):
    data = await request_site(post_form, auth("pmc"), url=url, label=" Documentation ")
    assert data["success"] is True
    assert data["site_name"] == "Apache HTTP Server - Documentation"
    assert data["site_url"] == expected_url
    assert matomo_api.calls[1][1]["siteName"] == "Apache HTTP Server - Documentation"
    assert len(sent_mail) == 1


async def test_name_falls_back_to_project_id_without_display_name(post_form, auth, matomo_api, monkeypatch):
    monkeypatch.setattr(config, "committee_names", {})
    data = await request_site(post_form, auth("pmc"))
    assert data["site_name"] == "Apache Httpd"


async def test_root_can_request_for_any_project(post_form, auth, matomo_api, sent_mail):
    data = await request_site(post_form, auth("root"), project="tomcat", url="https://tomcat.apache.org")
    assert data["success"] is True and data["site_name"] == "Apache Tomcat"
    assert sent_mail[0]["recipient"][1] == "private@tomcat.apache.org"


@pytest.mark.parametrize(
    "persona, form, message",
    [
        ("committer", {}, "Only members of a (P)PMC"),
        ("other-pmc", {}, "you are on the PMC of"),
        ("pmc", {"project": "nonexistent"}, "valid, current Apache project"),
        ("pmc", {"project": None}, "valid, current Apache project"),
        ("pmc", {"url": None}, "URL of the site"),
        ("pmc", {"url": "http://httpd.apache.org"}, "must start with https://"),
        ("pmc", {"url": "httpd.apache.org"}, "must start with https://"),
        ("pmc", {"url": "https://tomcat.apache.org"}, "on httpd.apache.org or one of its subdomains"),
        ("pmc", {"url": "https://evilhttpd.apache.org"}, "on httpd.apache.org or one of its subdomains"),
        ("pmc", {"url": "https://httpd.apache.org.evil.com"}, "on httpd.apache.org or one of its subdomains"),
        ("pmc", {"url": "https://httpd.apache.org/?x=1"}, "query string"),
        ("pmc", {"url": "https://httpd.apache.org/#top"}, "query string"),
        ("pmc", {"url": "https://httpd.apache.org:8443/"}, "plain https://"),
        ("pmc", {"url": "https://httpd.apache.org:notaport/"}, "valid site URL"),
        ("pmc", {"url": "https://bob@httpd.apache.org/"}, "plain https://"),
        ("pmc", {"url": "https://httpd.apache.org/a%20b"}, "path may only contain"),
        ("pmc", {"url": "https://httpd.apache.org/docs"}, "need a short label"),
        ("pmc", {"url": "https://httpd.apache.org/docs", "label": "<script>"}, "need a short label"),
        ("pmc", {"url": "https://httpd.apache.org/docs", "label": "x" * 41}, "need a short label"),
    ],
)
async def test_rejections(post_form, auth, matomo_api, sent_mail, persona, form, message):
    data = await request_site(post_form, auth(persona), **form)
    assert data["success"] is False and message in data["message"]
    assert not matomo_api.calls
    assert not sent_mail


async def test_unavailable_when_matomo_is_not_configured(post_form, auth, matomo_api, sent_mail, monkeypatch):
    monkeypatch.setattr(config.matomo, "token", None)
    data = await request_site(post_form, auth("pmc"))
    assert data["success"] is False and "not available" in data["message"]
    assert not matomo_api.calls and not sent_mail


async def test_existing_url_is_refused(post_form, auth, matomo_api, sent_mail):
    matomo_api.sites["httpd.apache.org"] = 7  # e.g. tracked as http://www.httpd.apache.org/
    data = await request_site(post_form, auth("pmc"))
    assert data["success"] is False
    assert "already exists" in data["message"] and "site ID 7" in data["message"]
    assert matomo_api.methods() == ["SitesManager.getSitesIdFromSiteUrl"]
    assert not sent_mail


async def test_second_request_for_same_url_is_refused(post_form, auth, matomo_api, sent_mail):
    first, second = await asyncio.gather(request_site(post_form, auth("pmc")), request_site(post_form, auth("pmc")))
    assert sorted([first["success"], second["success"]]) == [False, True]
    assert matomo_api.methods().count("SitesManager.addSite") == 1
    assert len(sent_mail) == 1


@pytest.mark.parametrize(
    "method, failure",
    [
        ("SitesManager.getSitesIdFromSiteUrl", (500, "Internal Server Error")),
        ("SitesManager.getSitesIdFromSiteUrl", aiohttp.ClientConnectionError("refused")),
        ("SitesManager.getSitesIdFromSiteUrl", asyncio.TimeoutError()),
        ("SitesManager.addSite", (200, {"result": "error", "message": "You can't access this resource"})),
        ("SitesManager.addSite", (200, {"value": "not-a-number"})),
    ],
)
async def test_matomo_failures_before_creation_are_errors(post_form, auth, matomo_api, sent_mail, method, failure):
    matomo_api.override[method] = failure
    data = await request_site(post_form, auth("pmc"))
    assert data == {"success": False, "message": matomo.MATOMO_ERROR}  # details are logged, not shown
    assert not sent_mail


async def test_access_failure_after_creation_still_succeeds(post_form, auth, matomo_api, sent_mail, capsys):
    matomo_api.override["UsersManager.setUserAccess"] = (200, {"result": "error", "message": "nope"})
    data = await request_site(post_form, auth("pmc"))
    assert data["success"] is True and data["tracking_code"]
    assert len(sent_mail) == 1
    assert "Needs attention: public (anonymous) view access could not be granted" in capsys.readouterr().out


async def test_anonymous_access_can_be_switched_off(post_form, auth, matomo_api, monkeypatch):
    monkeypatch.setattr(config.matomo, "anonymous_view", False)
    assert (await request_site(post_form, auth("pmc")))["success"] is True
    assert "UsersManager.setUserAccess" not in matomo_api.methods()


@pytest.mark.parametrize(
    "failure",
    [(200, {"result": "error", "message": "nope"}), (200, {"value": ""})],
)
async def test_missing_tracking_code_still_reports_site(post_form, auth, matomo_api, sent_mail, failure):
    matomo_api.override["SitesManager.getJavascriptTag"] = failure
    data = await request_site(post_form, auth("pmc"))
    assert data["success"] is True and data["site_id"] == 42
    assert data["tracking_code"] is None
    (mail,) = sent_mail
    assert "could not be retrieved automatically" in mail["message"]
    assert "Site ID:  42" in mail["message"]


async def test_entity_encoded_tracking_code_is_decoded(post_form, auth, matomo_api):
    matomo_api.override["SitesManager.getJavascriptTag"] = (200, {"value": "&lt;!-- Matomo --&gt;&lt;script&gt;&lt;/script&gt;"})
    data = await request_site(post_form, auth("pmc"))
    assert data["tracking_code"] == "<!-- Matomo --><script></script>"


async def test_public_feed_lists_project_display_names(client, monkeypatch):
    monkeypatch.setattr(config, "committee_names", {"httpd": "HTTP Server"})
    data = await (await client.get("/api/public")).get_json()
    assert data["project_names"] == {"httpd": "HTTP Server"}
