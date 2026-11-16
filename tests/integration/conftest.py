"""Fixtures for driving the real app through Quart's test client.

Authentication: requests carry `Authorization: Bearer <persona>`; the app's token
handler is swapped for one that maps persona names to sessions (see PERSONAS).
External services (mail, ACLI, infra-reports HTTP) are replaced with recorders;
the `sent_mail` and `http` fixtures live in tests/conftest.py so unit tests can use them too.
"""

import asyncio
import os
import shutil
import urllib.parse

import pytest

from app.lib import config

PERSONAS = {
    # httpd committer, not on any PMC
    "committer": {"uid": "alice", "fullname": "Alice", "projects": ["httpd"], "pmcs": []},
    # httpd PMC member
    "pmc": {"uid": "bob", "fullname": "Bob", "projects": ["httpd"], "pmcs": ["httpd"]},
    # PMC member of another project
    "other-pmc": {"uid": "carol", "fullname": "Carol", "projects": ["tomcat"], "pmcs": ["tomcat"]},
    "member": {"uid": "dave", "fullname": "Dave", "isMember": True, "projects": [], "pmcs": []},
    "chair": {"uid": "frank", "fullname": "Frank", "isChair": True, "projects": ["tomcat"], "pmcs": ["tomcat"]},
    "root": {"uid": "root-erin", "fullname": "Erin", "isRoot": True, "projects": [], "pmcs": []},
    "role": {"uid": "svc-mailreq", "fullname": "svc-mailreq role Account", "roleaccount": True},
}


@pytest.fixture
def auth():
    """auth("pmc") -> request headers that authenticate as that persona (see PERSONAS)."""

    def headers(persona: str) -> dict:
        assert persona in PERSONAS
        return {"Authorization": f"Bearer {persona}"}

    return headers


@pytest.fixture
def client(application, monkeypatch, sent_mail, tmp_path):  # pylint: disable=unused-argument
    """Test client with personas, known projects/mail domains, mail captured, clean queue and DBs."""

    async def persona_token_handler(token):
        return PERSONAS.get(token)

    monkeypatch.setattr(application, "token_handler", persona_token_handler)
    monkeypatch.setattr(config, "projects", ["httpd", "infra", "tomcat", "tooling"])
    monkeypatch.setattr(
        config.messaging,
        "mail_mappings",
        {
            "foundation": "apache.org",
            "httpd": "httpd.apache.org",
            "infra": "infra.apache.org",
            "tomcat": "tomcat.apache.org",
        },
    )
    monkeypatch.setattr(config.messaging, "mailing_lists", ["dev@httpd.apache.org"])

    _reset_storage()
    return application.test_client()


def _reset_storage():
    shutil.rmtree(config.storage.queue_dir, ignore_errors=True)
    os.makedirs(config.storage.queue_dir)
    from app.endpoints import confluenceaccount, jiraaccount  # pylint: disable=import-outside-toplevel

    for table in ("users", "pending", "blocked"):
        jiraaccount.JIRA_DB.runc(f"DELETE FROM {table}")
    for table in ("cwiki_users", "cwiki_pending", "cwiki_blocked"):
        confluenceaccount.CONFLUENCE_DB.runc(f"DELETE FROM {table}")


@pytest.fixture
def post_form(client):
    """POST an urlencoded form the way a browser does. Quart's test client leaves out
    Content-Length for form=, which asfquart's formdata() relies on."""

    async def post(path: str, form: dict, headers: dict | None = None):
        body = urllib.parse.urlencode(form).encode()
        all_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
            **(headers or {}),
        }
        return await client.post(path, data=body, headers=all_headers)

    return post


class FakeProcess:
    def __init__(self, returncode: int, stdout: bytes, stderr: bytes):
        self.returncode = returncode
        self._stdout, self._stderr = stdout, stderr

    async def communicate(self):
        return self._stdout, self._stderr

    async def wait(self):
        return self.returncode


class FakeACLI:
    """Stands in for asyncio.create_subprocess_exec. `calls` holds each argv (as a tuple).

    Default result is success; set `respond` to a callable(argv) -> (returncode, stdout, stderr).
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self.respond = lambda argv: (0, b"", b"")

    async def __call__(self, *argv, **_kwargs):
        self.calls.append(argv)
        return FakeProcess(*self.respond(argv))


@pytest.fixture
def acli(monkeypatch):
    fake = FakeACLI()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
    return fake
