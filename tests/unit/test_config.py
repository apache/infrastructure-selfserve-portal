"""Configuration parsing and the LDAP project-list refresh loop."""

import asyncio

import pytest

from app.lib import config


class StopLoop(Exception):
    """Raised from a patched asyncio.sleep to end an infinite background loop after one pass."""


async def _stop(_seconds):
    raise StopLoop


@pytest.mark.parametrize(
    "value, expected",
    [(512, 512), ("2048", 2048), ("5kb", 5 * 1024), ("5mb", 5 * 1024**2), ("2gb", 2 * 1024**3)],
)
def test_text_to_int(value, expected):
    assert config.text_to_int(value) == expected


def test_text_to_int_rejects_other_types():
    with pytest.raises(AssertionError):
        config.text_to_int(1.5)


def test_server_configuration_defaults_and_limits():
    cfg = config.ServerConfiguration({"bind": "::1", "port": "8080", "max_form_size": "2kb"})
    assert (cfg.bind, cfg.port) == ("::1", 8080)
    assert cfg.error_reporting == "show"
    assert cfg.max_form_size == 2048
    assert cfg.max_content_length == int(2048 * 1.34)  # room for base64 overhead
    assert cfg.debug_mode is False
    assert len(cfg.debug_password) == 8  # auto-generated when not configured


def test_server_configuration_requires_a_section_and_sane_form_size():
    with pytest.raises(AssertionError):
        config.ServerConfiguration({})
    with pytest.raises(AssertionError):
        config.ServerConfiguration({"bind": "::1", "port": 1, "max_form_size": 100})


def test_ldap_configuration_reads_role_accounts(tmp_path):
    accounts = tmp_path / "roleaccounts.txt"
    accounts.write_text("# comment\nsvc-one:pw1\nsvc-two:pw:with:colons\nnot-an-account\n")
    cfg = config.LDAPConfiguration(
        {"uri": "u", "groupbase": "g", "userbase": "u", "ldapbase": "l", "servicebase": "s", "roleaccounts": str(accounts)}
    )
    assert cfg.roleaccounts == {"svc-one": "pw1", "svc-two": "pw:with:colons"}


def test_database_configurations():
    assert config.JiraPSQLConfiguration({}).yaml == {}
    with pytest.raises(AssertionError):
        config.JiraPSQLConfiguration({"host": "h"})
    cwiki = config.CwikiMySQLConfiguration({"host": "h", "user": "u", "password": "p", "dbname": "cwiki"})
    assert cwiki.yaml == {"host": "h", "user": "u", "password": "p", "db": "cwiki"}  # aiomysql calls it "db"


@pytest.fixture
def ldap_projects(monkeypatch):
    """Run get_projects_from_ldap once against a fake LDAP answer; returns (setter, project list)."""
    projects = ["old-project"]
    monkeypatch.setattr(config, "projects", projects)
    monkeypatch.setattr(config.asyncio, "sleep", _stop)

    async def no_mappings():
        return None

    monkeypatch.setattr(config, "fetch_committee_mappings", no_mappings)

    def answer_with(entries):
        async def fake_ldapsearch(*_args, **_kwargs):
            return entries

        monkeypatch.setattr(config.asfpy.clitools, "ldapsearch_cli_async", fake_ldapsearch)

    return answer_with, projects


async def test_ldap_refresh_replaces_project_list(ldap_projects):
    answer_with, projects = ldap_projects
    answer_with([{"cn": [f"project{i:03}"]} for i in range(150)])
    with pytest.raises(StopLoop):
        await config.get_projects_from_ldap()
    assert len(projects) == 152
    assert "old-project" not in projects
    assert {"infra", "tooling", "project000"} <= set(projects)
    assert projects == sorted(projects)


async def test_ldap_refresh_keeps_list_when_answer_is_too_small(ldap_projects):
    """Regression: a short LDAP answer used to raise UnboundLocalError and kill the loop."""
    answer_with, projects = ldap_projects
    answer_with([{"cn": ["only-one"]}])
    with pytest.raises(StopLoop):  # i.e. the loop survived to its sleep
        await config.get_projects_from_ldap()
    assert projects == ["old-project"]


async def test_ldap_refresh_survives_timeouts(ldap_projects, monkeypatch):
    _answer_with, projects = ldap_projects

    async def timeout(awaitable, *_args, **_kwargs):
        awaitable.close()  # never started; close it so it isn't reported as un-awaited
        raise asyncio.exceptions.TimeoutError

    monkeypatch.setattr(config.asyncio, "wait_for", timeout)
    with pytest.raises(StopLoop):
        await config.get_projects_from_ldap()
    assert projects == ["old-project"]
