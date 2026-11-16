"""Email templating and the shipped templates themselves."""

import pathlib
import string

import pytest

from app.lib import config, email

TEMPLATES = sorted(pathlib.Path(config.messaging.template_dir).glob("*.txt"))


def test_templates_are_present():
    assert len(TEMPLATES) >= 15


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_template_is_well_formed(template):
    """Every template must split into subject and body and be valid str.format syntax."""
    subject, sep, body = template.read_text().partition("--")
    assert sep, "missing '--' separator between subject and body"
    assert subject.strip() and "\n" not in subject.strip(), "subject must be a single non-empty line"
    assert body.strip()
    list(string.Formatter().parse(subject + body))  # raises ValueError on stray braces


def test_from_template_formats_and_sends(sent_mail):
    email.from_template(
        "mailinglist_create.txt",
        recipient="someone@example.org",
        variables={"listpart": "dev", "domainpart": "httpd.apache.org", "requester": "alice"},
        thread_start=True,
        thread_key="key-1",
    )
    (mail,) = sent_mail
    assert mail["recipient"] == "someone@example.org"
    assert mail["sender"] == config.messaging.sender
    assert mail["host"] == "mail.invalid"
    assert (mail["thread_start"], mail["thread_key"]) == (True, "key-1")
    assert "dev@httpd.apache.org" in mail["subject"] + mail["message"]
    assert "{" not in mail["subject"]


def test_from_template_requires_all_variables(sent_mail):
    with pytest.raises(KeyError):
        email.from_template("mailinglist_create.txt", recipient="x@example.org", variables={})
    assert not sent_mail


def test_from_template_rejects_unknown_template(sent_mail):
    with pytest.raises(AssertionError):
        email.from_template("no-such-template.txt", recipient="x@example.org", variables={})


def test_project_to_private(monkeypatch):
    monkeypatch.setattr(config.messaging, "mail_mappings", {"httpd": "httpd.apache.org"})
    assert email.project_to_private("httpd") == "private@httpd.apache.org"
    assert email.project_to_private("unknown") == "private@infra.apache.org"
