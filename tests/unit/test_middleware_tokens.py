"""Small pieces of request plumbing: the filename URL converter and role-account tokens."""

import pytest

from app.lib import middleware, tokens


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("report.json", ("report", "json")),
        ("archive.tar.gz", ("archive", "tar.gz")),
        ("README", ("README", "")),
        (".htaccess", (".htaccess", "")),  # leading dot is not an extension separator
    ],
)
def test_filename_converter(raw, expected):
    assert middleware.FilenameConverter(None).to_python(raw) == expected


async def test_role_account_token_maps_to_role_session(monkeypatch):
    monkeypatch.setattr(tokens, "roleaccounts", {"tok-123": "svc-mailreq"})
    session = await tokens.token_handler("tok-123")
    assert session == {"uid": "svc-mailreq", "fullname": "svc-mailreq role Account", "roleaccount": True}


async def test_unknown_token_gives_no_session(monkeypatch):
    monkeypatch.setattr(tokens, "roleaccounts", {"tok-123": "svc-mailreq"})
    assert await tokens.token_handler("guess") is None
