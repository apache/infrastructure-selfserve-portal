"""Configuration parsing and the refresh loops for projects, mail domains and mailing lists."""

import asyncio
import json

import pytest

from app.lib import config


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
def ldap_projects(monkeypatch, one_pass):  # pylint: disable=unused-argument
    """Run get_projects_from_ldap once against a fake LDAP answer; returns (setter, project list)."""
    projects = ["old-project"]
    monkeypatch.setattr(config, "projects", projects)

    async def no_mappings():
        return None

    monkeypatch.setattr(config, "fetch_committee_mappings", no_mappings)

    def answer_with(entries):
        async def fake_ldapsearch(*_args, **_kwargs):
            return entries

        monkeypatch.setattr(config.asfpy.clitools, "ldapsearch_cli_async", fake_ldapsearch)

    return answer_with, projects


async def test_ldap_refresh_replaces_project_list(ldap_projects, one_pass):
    answer_with, projects = ldap_projects
    answer_with([{"cn": [f"project{i:03}"]} for i in range(150)])
    with pytest.raises(one_pass):
        await config.get_projects_from_ldap()
    assert len(projects) == 152
    assert "old-project" not in projects
    assert {"infra", "tooling", "project000"} <= set(projects)
    assert projects == sorted(projects)


async def test_ldap_refresh_keeps_list_when_answer_is_too_small(ldap_projects, one_pass):
    """Regression: a short LDAP answer used to raise UnboundLocalError and kill the loop."""
    answer_with, projects = ldap_projects
    answer_with([{"cn": ["only-one"]}])
    with pytest.raises(one_pass):  # i.e. the loop survived to its sleep
        await config.get_projects_from_ldap()
    assert projects == ["old-project"]


async def test_ldap_refresh_survives_timeouts(ldap_projects, monkeypatch, one_pass):
    _answer_with, projects = ldap_projects

    async def timeout(awaitable, *_args, **_kwargs):
        awaitable.close()  # never started; close it so it isn't reported as un-awaited
        raise asyncio.exceptions.TimeoutError

    monkeypatch.setattr(config.asyncio, "wait_for", timeout)
    with pytest.raises(one_pass):
        await config.get_projects_from_ldap()
    assert projects == ["old-project"]


# --- mailing lists (webmod) and project mail domains (whimsy) -----------------------

WEBMOD = config.cfg_yaml["webmod_list_url"]


@pytest.fixture
def mailing_lists(monkeypatch):
    monkeypatch.setattr(config.messaging, "mailing_lists", ["dev@old.apache.org"])


async def test_mailing_list_refresh_replaces_known_lists(http, one_pass, mailing_lists):
    http.routes[WEBMOD] = (200, ["dev@httpd.apache.org", "users@httpd.apache.org"])
    with pytest.raises(one_pass):
        await config.fetch_valid_lists()
    assert config.messaging.mailing_lists == ["dev@httpd.apache.org", "users@httpd.apache.org"]


@pytest.mark.parametrize(
    "answer",
    [(503, "Service Unavailable"), (200, json.JSONDecodeError("garbled", "<html>", 0))],
    ids=["http-error", "invalid-json"],
)
async def test_mailing_list_refresh_keeps_known_lists_on_failure(http, one_pass, mailing_lists, answer):
    """The list guards against creating duplicates, so a webmod outage must not empty it."""
    http.routes[WEBMOD] = answer
    with pytest.raises(one_pass):  # i.e. the loop survived to its sleep
        await config.fetch_valid_lists()
    assert config.messaging.mailing_lists == ["dev@old.apache.org"]


@pytest.fixture
def mail_mappings(monkeypatch):
    monkeypatch.setattr(config, "projects", ["httpd", "infra", "newpodling"])
    monkeypatch.setattr(config.messaging, "mail_mappings", {"stale": "stale.apache.org"})
    monkeypatch.setattr(config, "committee_names", {"stale": "Stale"})


async def test_committee_mappings_use_whimsy_mail_list_names(http, mail_mappings):
    """These mappings decide which domains a PMC member may create mailing lists on."""
    committees = {"httpd": {"mail_list": "httpd"}, "infra": {"mail_list": "infrastructure"}}
    http.routes[config.WHIMSY_COMMITTEE_URL] = (200, {"committees": committees})
    await config.fetch_committee_mappings()
    assert config.messaging.mail_mappings == {
        "foundation": "apache.org",
        "apachecon": "apachecon.com",
        "httpd": "httpd.apache.org",
        "infra": "infrastructure.apache.org",  # whimsy's mail_list wins over the LDAP name
        "newpodling": "newpodling.apache.org",  # unknown to whimsy: falls back to the LDAP name
    }


@pytest.mark.parametrize(
    "answer",
    [(500, "oops"), (200, json.JSONDecodeError("garbled", "<html>", 0)), (200, {"unexpected": "shape"})],
    ids=["http-error", "invalid-json", "no-committees-key"],
)
async def test_committee_mappings_are_kept_when_whimsy_fails(http, mail_mappings, answer):
    http.routes[config.WHIMSY_COMMITTEE_URL] = answer
    await config.fetch_committee_mappings()
    assert config.messaging.mail_mappings == {"stale": "stale.apache.org"}


def test_matomo_configuration_reads_credentials_file(tmp_path):
    credentials = tmp_path / "matomo.yaml"
    credentials.write_text("url: https://analytics-dev.example.org\ntoken: abc123\n")
    cfg = config.MatomoConfiguration({"credentials": str(credentials)})
    assert cfg.url == "https://analytics-dev.example.org/"  # always ends in a slash
    assert cfg.token == "abc123"
    assert cfg.enabled and cfg.anonymous_view


@pytest.mark.parametrize("contents", [None, "url: https://analytics.example.org/\n", "token: abc\n", ""])
def test_matomo_configuration_is_disabled_without_complete_credentials(tmp_path, contents):
    credentials = tmp_path / "matomo.yaml"
    if contents is not None:
        credentials.write_text(contents)
    cfg = config.MatomoConfiguration({"credentials": str(credentials), "anonymous_view": False})
    assert not cfg.enabled
    assert cfg.anonymous_view is False
    assert not config.MatomoConfiguration({}).enabled


def test_matomo_configuration_rejects_a_malformed_credentials_file(tmp_path):
    credentials = tmp_path / "matomo.yaml"
    credentials.write_text("- just\n- a list\n")
    with pytest.raises(AssertionError):
        config.MatomoConfiguration({"credentials": str(credentials)})


async def test_committee_mappings_record_display_names(http, mail_mappings):
    """Display names give Matomo properties their names, e.g. "Apache HTTP Server"."""
    committees = {"httpd": {"mail_list": "httpd", "display_name": "HTTP Server"}, "infra": {"mail_list": "infrastructure"}}
    http.routes[config.WHIMSY_COMMITTEE_URL] = (200, {"committees": committees})
    await config.fetch_committee_mappings()
    assert config.committee_names == {"httpd": "HTTP Server"}
