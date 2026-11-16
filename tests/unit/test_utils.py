"""Input validators shared by the account and mailing-list endpoints."""

import pytest

from app.lib import utils


@pytest.mark.parametrize("address", ["a@b.c", "aZZZ@b.c.d.e.f", "first.last+tag@example.org"])
def test_valid_email_addresses(address):
    assert utils.check_email_address(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "a@bc",  # domain needs a dot
        "a@b.c@d.e",  # only one @
        "no-at-sign.example.org",
        "has space@example.org",
        "@example.org",  # empty local part
    ],
)
def test_invalid_email_addresses(address):
    assert utils.check_email_address(address) is False


@pytest.mark.parametrize("uid", ["abcd", "a2345678901234567890", "humbedooh"])
def test_valid_user_ids(uid):
    assert utils.check_user_id_syntax(uid) is True


@pytest.mark.parametrize(
    "uid",
    [
        "abc",  # too short
        "0abc",  # must start with a letter
        "Abcd",  # lowercase only
        "ab-cd",  # alphanumeric only
        "a" * 22,
    ],
)
def test_invalid_user_ids(uid):
    assert utils.check_user_id_syntax(uid) is False


def test_user_id_length_upper_bound_is_21():
    """Documents current behaviour: the regex accepts 21 characters although
    VALID_USERNAME_MSG says 4-20. Change this test if the validator is fixed."""
    assert utils.check_user_id_syntax("a" * 21) is True
    assert "4-20" in utils.VALID_USERNAME_MSG


def test_jira_and_confluence_ids_follow_the_generic_rule():
    for check in (utils.check_jira_id_syntax, utils.check_confluence_id_syntax):
        assert check("validname") is True
        assert check("0invalid") is False
