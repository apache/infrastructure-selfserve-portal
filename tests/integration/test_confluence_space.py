"""Confluence space creation and archiving: ASF members and chairs only, done through ACLI.

Archiving strips every existing permission from a space, so the order of the ACLI calls
and stopping at the first failure both matter.
"""

import pytest

from app.endpoints import confluence_archive, confluence_create

OWNERS = b'[{"idType": "user", "id": "alice"}, {"idType": "group", "id": "httpd-pmc"}, {"idType": "other", "id": "x"}]'


def actions(acli):
    return [argv[argv.index("--action") + 1] for argv in acli.calls]


def option(argv, name):
    return argv[argv.index(name) + 1]


def fail_on(action, otherwise=(0, b"", b"")):
    """An ACLI responder that fails the given action and succeeds for the rest."""
    return lambda argv: (1, b"", b"boom") if action in argv else otherwise


# --- access ------------------------------------------------------------------------

ENDPOINTS = {
    "/api/confluence-archive": {"space": "HTTPDOLD"},
    "/api/confluence-create": {"space": "HTTPDNEW", "admin": "dave", "description": "A new space"},
}


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_requires_login(client, acli, path):
    assert (await client.post(path, json=ENDPOINTS[path])).status_code == 302  # sent to OAuth login
    assert not acli.calls


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize("persona", ["committer", "pmc", "role"])
async def test_requires_member_or_chair(client, auth, acli, sent_mail, path, persona):
    resp = await client.post(path, json=ENDPOINTS[path], headers=auth(persona))
    assert resp.status_code == 403
    assert not acli.calls
    assert not sent_mail


# --- archiving ---------------------------------------------------------------------


async def archive(client, headers, space="HTTPDOLD"):
    resp = await client.post("/api/confluence-archive", json={"space": space}, headers=headers)
    return await resp.get_json()


@pytest.mark.parametrize("persona, uid", [("member", "dave"), ("chair", "frank")])
async def test_archive_makes_space_read_only(client, auth, acli, sent_mail, persona, uid):
    acli.respond = lambda argv: (0, OWNERS if "getSpacePermissionList" in argv else b"", b"")
    assert await archive(client, auth(persona)) == {"success": True, "message": "Confluence space archived"}

    assert all(argv[0] == confluence_archive.ACLI_CMD and option(argv, "--space") == "HTTPDOLD" for argv in acli.calls)
    assert actions(acli) == [
        "getSpacePermissionList",
        "updateSpace",
        "removePermissions",  # users
        "removePermissions",  # groups
        "addPermissions",  # anonymous read
        "addPermissions",  # logged-in read + export
    ]
    _, status, drop_users, drop_groups, anonymous, logged_in = acli.calls
    assert option(status, "--options") == "status=archived"
    assert (option(drop_users, "--userId"), option(drop_users, "--permissions")) == ("alice", "@all")
    assert (option(drop_groups, "--group"), option(drop_groups, "--permissions")) == ("httpd-pmc", "@all")
    assert (option(anonymous, "--userId"), option(anonymous, "--permissions")) == ("Anonymous", "VIEWSPACE")
    assert (option(logged_in, "--group"), option(logged_in, "--permissions")) == (
        "confluence-users",
        "VIEWSPACE,EXPORTSPACE",
    )

    (mail,) = sent_mail
    assert mail["recipient"] == ("private@infra.apache.org", f"{uid}@apache.org")
    assert "HTTPDOLD" in mail["subject"] + mail["message"]


@pytest.mark.parametrize("space", ["httpdold", "HTTPD OLD", "HTTPD-OLD", "", *confluence_archive.PROTECTED_SPACES])
async def test_archive_rejects_invalid_and_protected_spaces(client, auth, acli, sent_mail, space):
    data = await archive(client, auth("member"), space)
    assert data["success"] is False
    assert not acli.calls
    assert not sent_mail


async def test_archive_of_unknown_space_changes_nothing(client, auth, acli, sent_mail):
    # ACLI prints nothing for a space it cannot find (the default fake response).
    data = await archive(client, auth("member"))
    assert data == {"success": False, "message": "Could not find this confluence space"}
    assert actions(acli) == ["getSpacePermissionList"]
    assert not sent_mail


@pytest.mark.parametrize(
    "failing, completed",
    [
        ("updateSpace", ["getSpacePermissionList", "updateSpace"]),
        ("removePermissions", ["getSpacePermissionList", "updateSpace", "removePermissions"]),
        (
            "addPermissions",
            ["getSpacePermissionList", "updateSpace", "removePermissions", "removePermissions", "addPermissions"],
        ),
    ],
)
async def test_archive_stops_at_first_acli_failure(client, auth, acli, sent_mail, failing, completed):
    acli.respond = fail_on(failing, otherwise=(0, OWNERS, b""))
    data = await archive(client, auth("member"))
    assert data == {"success": False, "message": confluence_archive.CONFLUENCE_ERROR}
    assert actions(acli) == completed
    assert not sent_mail  # nobody is told a half-finished archive succeeded


# --- creation ----------------------------------------------------------------------


async def create(client, headers, **overrides):
    body = {**ENDPOINTS["/api/confluence-create"], **overrides}
    resp = await client.post("/api/confluence-create", json=body, headers=headers)
    return await resp.get_json()


async def test_create_sets_up_space_with_default_permissions(client, auth, acli, sent_mail):
    assert await create(client, auth("member")) == {"success": True, "message": "Confluence space created"}

    assert all(argv[0] == confluence_create.ACLI_CMD for argv in acli.calls)
    assert actions(acli) == [
        "getUser",
        "addSpace",
        "addPermissions",  # admin
        "addPermissions",  # anonymous read
        "addPermissions",  # logged-in read + export
        "removePermissions",  # the bot that created the space
    ]
    lookup, add, admin, anonymous, logged_in, bot = acli.calls
    assert option(lookup, "--userId") == "dave"
    assert (option(add, "--space"), option(add, "--description")) == ("HTTPDNEW", "A new space")
    assert (option(admin, "--userId"), option(admin, "--permissions")) == ("dave", "@all")
    assert (option(anonymous, "--userId"), option(anonymous, "--permissions")) == ("Anonymous", "VIEWSPACE")
    assert (option(logged_in, "--group"), option(logged_in, "--permissions")) == (
        "confluence-users",
        "VIEWSPACE,EXPORTSPACE",
    )
    assert (option(bot, "--userId"), option(bot, "--permissions")) == ("infrabot", "@all")

    (mail,) = sent_mail
    assert mail["recipient"] == ("private@infra.apache.org", "dave@apache.org")
    assert "HTTPDNEW" in mail["subject"] + mail["message"]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"space": "httpd new"}, "Invalid space name"),
        ({"space": None}, "Invalid space name"),
        ({"admin": ""}, "initial administrator"),
        ({"description": ""}, "short description"),
    ],
)
async def test_create_validation(client, auth, acli, sent_mail, overrides, message):
    data = await create(client, auth("member"), **overrides)
    assert data["success"] is False and message in data["message"]
    assert not acli.calls
    assert not sent_mail


@pytest.mark.parametrize(
    "failing, message, completed",
    [
        ("getUser", "administrator ID", ["getUser"]),
        ("addSpace", "may already exist", ["getUser", "addSpace"]),
        ("addPermissions", confluence_create.CONFLUENCE_ERROR, ["getUser", "addSpace", "addPermissions"]),
    ],
)
async def test_create_stops_at_first_acli_failure(client, auth, acli, sent_mail, failing, message, completed):
    acli.respond = fail_on(failing)
    data = await create(client, auth("member"))
    assert data["success"] is False and message in data["message"]
    assert actions(acli) == completed
    assert not sent_mail
