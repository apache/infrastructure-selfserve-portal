"""Background loops: pruning of stale account requests and the Jira/Confluence email-map loaders.

The loops never run during tests (see tests/conftest.py); each test drives one pass by
hand with `one_pass`, which makes the loop's sleep raise.
"""

import time

import aiomysql
import psycopg
import pytest

from app.endpoints import confluence_activate_account, confluenceaccount, jira_activate_account, jiraaccount

DAY = 86400


def test_every_background_loop_is_registered(application):
    registered = {f"{task.__module__}.{task.__name__}" for task in application.deferred_background_tasks}
    assert registered == {
        "app.endpoints.jiraaccount.prune_stale_requests",
        "app.endpoints.confluenceaccount.prune_stale_requests",
        "app.endpoints.jira_activate_account.update_jira_email_map",
        "app.endpoints.confluence_activate_account.update_confluence_email_map",
    }


# --- pruning -----------------------------------------------------------------------

PENDING_STORES = {
    "jira": (jiraaccount, jiraaccount.JIRA_DB, "pending"),
    "confluence": (confluenceaccount, confluenceaccount.CONFLUENCE_DB, "cwiki_pending"),
}


def pending_request(userid: str, created: int, denied_ts: int = 0) -> dict:
    return {
        "userid": userid,
        "token": f"token-{userid}",
        "realname": "Some One",
        "email": f"{userid}@example.org",
        "project": "httpd",
        "why": "I would like to report a bug.",
        "created": created,
        "userip": "192.0.2.1",
        "validated": 1,
        "denied_ts": denied_ts,
    }


@pytest.mark.parametrize("service", PENDING_STORES)
async def test_pruning_removes_only_stale_requests(client, one_pass, service):  # pylint: disable=unused-argument
    module, database, table = PENDING_STORES[service]
    now = int(time.time())
    for request in (
        pending_request("fresh", created=now - DAY),
        pending_request("waiting", created=now - 89 * DAY),  # still inside the 90-day window
        pending_request("abandoned", created=now - 91 * DAY),
        pending_request("justdenied", created=now - 2 * DAY, denied_ts=now - 3600),  # 24h to reconsider
        pending_request("longdenied", created=now - 2 * DAY, denied_ts=now - DAY - 60),
    ):
        database.insert(table, request)

    with pytest.raises(one_pass):
        await module.prune_stale_requests()

    assert sorted(row["userid"] for row in database.fetch(table, limit=100)) == ["fresh", "justdenied", "waiting"]


# --- userid -> email maps used by account reactivation ------------------------------

DIRECTORY = [
    ("alice", "alice@example.org"),
    ("bob", "Bob@Example.org"),
    ("noemail", None),  # privacy-redacted address
    ("blank", ""),
    (None, "nobody@example.org"),
]
USABLE = {"alice": "alice@example.org", "bob": "Bob@Example.org"}


class FakeCursor:
    def __init__(self, rows, error=None):
        self.rows, self.error, self.queries = rows, error, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, query):
        self.queries.append(query)
        if self.error:
            raise self.error

    async def __aiter__(self):
        for row in self.rows:
            yield row


class FakeConnection:
    """Stands in for a psycopg connection, an aiomysql pool and an aiomysql connection."""

    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def cursor(self):
        return self._cursor

    def acquire(self):
        return self


@pytest.fixture
def jira_db(monkeypatch):
    """jira_db(rows) / jira_db(error=...) -> what the next connection attempt to Jira's Postgres gives."""
    monkeypatch.setattr(jira_activate_account, "JIRA_EMAIL_MAPPINGS", {"stale": "stale@example.org"})

    def answer(rows=(), error=None):
        cursor = FakeCursor(rows)

        async def connect(_dsn):
            if error:
                raise error
            return FakeConnection(cursor)

        monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
        return cursor

    return answer


async def test_jira_email_map_is_replaced_with_usable_rows(jira_db, one_pass):
    cursor = jira_db(DIRECTORY)
    with pytest.raises(one_pass):
        await jira_activate_account.update_jira_email_map()
    assert jira_activate_account.JIRA_EMAIL_MAPPINGS == USABLE
    assert "directory_id != 10000" in cursor.queries[0]  # LDAP-backed (ASF) accounts are excluded


async def test_jira_email_map_survives_database_outage(jira_db, one_pass):
    jira_db(error=psycopg.OperationalError("connection refused"))
    with pytest.raises(one_pass):  # i.e. the loop survived to its sleep
        await jira_activate_account.update_jira_email_map()
    assert jira_activate_account.JIRA_EMAIL_MAPPINGS == {"stale": "stale@example.org"}


@pytest.fixture
def confluence_db(monkeypatch):
    """confluence_db(rows) / confluence_db(error=...) / confluence_db(connect_error=...) -> how Confluence's MySQL answers."""
    monkeypatch.setattr(confluence_activate_account, "CONFLUENCE_EMAIL_MAPPINGS", {"stale": "stale@example.org"})

    def answer(rows=(), error=None, connect_error=None):
        cursor = FakeCursor(rows, error)

        async def create_pool(**_kwargs):
            if connect_error:
                raise connect_error
            return FakeConnection(cursor)

        monkeypatch.setattr(aiomysql, "create_pool", create_pool)
        return cursor

    return answer


async def test_confluence_email_map_is_replaced_with_usable_rows(confluence_db, one_pass):
    cursor = confluence_db(DIRECTORY)
    with pytest.raises(one_pass):
        await confluence_activate_account.update_confluence_email_map()
    assert confluence_activate_account.CONFLUENCE_EMAIL_MAPPINGS == USABLE
    assert "directory_id != 10000" in cursor.queries[0]


async def test_confluence_email_map_survives_failed_query(confluence_db, one_pass):
    confluence_db(error=aiomysql.OperationalError(2013, "Lost connection to MySQL server during query"))
    with pytest.raises(one_pass):
        await confluence_activate_account.update_confluence_email_map()
    assert confluence_activate_account.CONFLUENCE_EMAIL_MAPPINGS == {"stale": "stale@example.org"}


async def test_confluence_email_map_retries_when_database_is_down_at_startup(confluence_db, monkeypatch):
    """Regression: the pool was created outside the retry, so an outage at startup killed the loader for good."""
    confluence_db(connect_error=aiomysql.OperationalError(2003, "Can't connect to MySQL server"))
    passes = []

    class TwoPassesDone(Exception):
        pass

    async def database_comes_back_then_stop(_seconds):
        passes.append(dict(confluence_activate_account.CONFLUENCE_EMAIL_MAPPINGS))
        if len(passes) == 2:
            raise TwoPassesDone
        confluence_db(DIRECTORY)

    monkeypatch.setattr(confluence_activate_account.asyncio, "sleep", database_comes_back_then_stop)
    with pytest.raises(TwoPassesDone):
        await confluence_activate_account.update_confluence_email_map()
    assert passes == [{"stale": "stale@example.org"}, USABLE]
