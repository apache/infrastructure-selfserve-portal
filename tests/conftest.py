"""Shared test setup for the selfserve portal.

The app reads its configuration, creates directories and opens SQLite databases at
*import* time, and resolves several paths relative to the working directory (it is
normally run from server/). So before anything from server/app is imported we:

- write a throwaway config into a temp dir and point SELFSERVE_CONFIG at it,
- import and build the app from <tmp>/root/server (cwd is restored afterwards), with
  <tmp>/root/htdocs symlinked to the real htdocs, so cwd-relative paths resolve the way
  they do in production and nothing the app writes (apptoken.txt, DBs, queue) lands in the repo,
- put server/ on sys.path so `import app` works.
"""

import os
import pathlib
import sys
import tempfile

import aiohttp
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVER = REPO / "server"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="selfserve-tests-"))

(TMP / "root" / "server").mkdir(parents=True)
(TMP / "root" / "htdocs").symlink_to(REPO / "htdocs", target_is_directory=True)
(TMP / "roleaccounts.txt").write_text("# role accounts for tests\nsvc-mailreq:s3cret\n")

TEST_CONFIG = {
    "server": {
        "bind": "127.0.0.1",
        "port": 8000,
        "error_reporting": "show",
        "max_form_size": "1mb",
        "rate_limit_per_ip": 0,
    },
    "ldap": {
        "uri": "ldaps://ldap.invalid:636",
        "userbase": "uid=%s,ou=people,dc=apache,dc=org",
        "groupbase": "cn=%s,ou=project,ou=groups,dc=apache,dc=org",
        "servicebase": "cn=%s,ou=groups,ou=services,dc=apache,dc=org",
        "ldapbase": "dc=apache,dc=org",
        "roleaccounts": str(TMP / "roleaccounts.txt"),
    },
    "storage": {
        "queue_dir": str(TMP / "queue"),
        "db_dir": str(TMP / "db"),
    },
    "messaging": {
        "sender": "ASF Self-serve Portal <no-reply@apache.org>",
        "template_dir": str(SERVER / "email_templates"),
        "mail_relay": "mail.invalid",
    },
    "webmod_list_url": "http://webmod.invalid/lists",
}
(TMP / "selfserve-portal.yaml").write_text(yaml.safe_dump(TEST_CONFIG))

os.environ["SELFSERVE_CONFIG"] = str(TMP / "selfserve-portal.yaml")
sys.path.insert(0, str(SERVER))


def pytest_collection_modifyitems(items):
    """Mark tests by directory, so `-m unit` / `-m integration` select them."""
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        elif "integration" in parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def sent_mail(monkeypatch):
    """Capture outgoing email instead of talking to an MTA. Returns a list of mail() kwargs."""
    import asfpy.messaging

    sent: list[dict] = []
    monkeypatch.setattr(asfpy.messaging, "mail", lambda **kwargs: sent.append(kwargs))
    return sent


class FakeResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        if isinstance(self._payload, Exception):  # e.g. a JSONDecodeError for a garbled body
            raise self._payload
        return self._payload

    async def text(self):
        return str(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakeHTTP:
    """Replacement for aiohttp.ClientSession.

    GETs are routed by URL to (status, json payload) and recorded in `requests`.
    POSTs always succeed and are recorded in `posts` as (url, kwargs).
    """

    routes: dict = {}
    requests: list = []
    posts: list = []

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def get(self, url, params=None, **_kwargs):
        FakeHTTP.requests.append((url, params))
        status, payload = FakeHTTP.routes[url]
        return FakeResponse(status, payload)

    async def post(self, url, **kwargs):
        FakeHTTP.posts.append((url, kwargs))
        return FakeResponse(200, {"ok": True})


@pytest.fixture
def http(monkeypatch):
    """Replace aiohttp.ClientSession with FakeHTTP; nothing reaches the network."""
    FakeHTTP.routes = {}
    FakeHTTP.requests = []
    FakeHTTP.posts = []
    monkeypatch.setattr(aiohttp, "ClientSession", FakeHTTP)
    return FakeHTTP


class StopLoop(Exception):
    """Raised from a patched asyncio.sleep to end an infinite background loop after one pass."""


@pytest.fixture
def one_pass(monkeypatch):
    """Make `while True: ...; await asyncio.sleep(n)` loops stop at their first sleep.

    Usage: `with pytest.raises(one_pass): await some_loop()`; reaching the sleep means
    the loop body completed without dying.
    """
    import asyncio  # pylint: disable=import-outside-toplevel

    async def stop(_seconds):
        raise StopLoop

    monkeypatch.setattr(asyncio, "sleep", stop)
    return StopLoop


def _build_app():
    """The real Quart app with all endpoint modules registered.

    Built while conftest is imported, i.e. before test modules are collected, because the
    endpoint modules register routes on asfquart.APP at import time. Background tasks
    (LDAP/webmod refresh, DB pruning, email-map loaders) are recorded, not started, so no
    test talks to an external service by accident.
    """
    import app as selfserve  # pylint: disable=import-outside-toplevel

    quart_app = selfserve.main()
    quart_app.config["TESTING"] = True
    # Unhandled errors become 500 responses (logged with traceback), as in production.
    quart_app.config["PROPAGATE_EXCEPTIONS"] = False
    quart_app.deferred_background_tasks = []
    real_add_background_task = quart_app.add_background_task
    quart_app.add_background_task = quart_app.deferred_background_tasks.append
    try:
        import app.endpoints  # noqa: F401  # pylint: disable=unused-import,import-outside-toplevel
        import app.lib.tokens  # noqa: F401  # pylint: disable=unused-import,import-outside-toplevel
    finally:
        quart_app.add_background_task = real_add_background_task
    return quart_app


_cwd = os.getcwd()
os.chdir(TMP / "root" / "server")
try:
    APPLICATION = _build_app()
finally:
    os.chdir(_cwd)


@pytest.fixture(scope="session")
def application():
    return APPLICATION
