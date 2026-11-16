"""POST /api/mailinglist: request validation, authorisation and the queued request."""

import json
import os
import time

import pytest

from app.lib import config


def request(**overrides):
    body = {
        "listpart": "commits",
        "domainpart": "httpd.apache.org",
        "moderators": ["mod1@example.org", "mod2@example.org"],
        "muopts": "mu",
        "private": False,
        "trailer": True,
    }
    body.update(overrides)
    return body


def queued(name="mailinglist-commits-httpd.apache.org.json"):
    path = os.path.join(config.storage.queue_dir, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def test_requires_pmc_membership(client, auth):
    assert (await client.post("/api/mailinglist", json=request())).status_code == 302
    resp = await client.post("/api/mailinglist", json=request(), headers=auth("committer"))
    assert resp.status_code == 403
    assert queued() is None


async def test_pmc_member_queues_a_list(client, auth, sent_mail):
    before = int(time.time())
    resp = await client.post("/api/mailinglist", json=request(), headers=auth("pmc"))
    assert (await resp.get_json())["success"] is True

    payload = queued()
    assert payload["type"] == "mailinglist"
    assert payload["id"] == "mailinglist-commits-httpd.apache.org.json"
    assert (payload["list"], payload["domain"]) == ("commits", "httpd.apache.org")
    assert payload["requester"] == "bob"
    assert payload["mods"] == ["mod1@example.org", "mod2@example.org"]
    assert payload["trailer"] == "t"
    assert payload["requested"] >= before
    assert payload["private"] is False

    (mail,) = sent_mail
    assert mail["recipient"] == ("private@infra.apache.org", "bob@apache.org")


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"listpart": "Bad_Name"}, "Invalid list name"),
        ({"listpart": "commits-digest"}, "cannot end in -digest"),
        ({"listpart": "commits-owner"}, "restricted ezmlm keyword"),
        ({"domainpart": "example.com"}, "not a valid ASF hostname"),
        ({"domainpart": "tomcat.apache.org"}, "not authorized to create mailing lists for this domain"),
        ({"moderators": []}, "list of moderators"),
        ({"moderators": ["not-an-address"]}, "Invalid moderator list"),
        ({"muopts": "MU"}, "Invalid moderation options"),
        ({"trailer": "yes"}, "Trailer option must be a boolean"),
        ({"listpart": "dev"}, "already exists"),
        ({"listpart": "private", "private": False}, "MUST be marked as private"),
        ({"listpart": "board", "private": True}, "Only private@ or security@ can be made private"),
        ({"expedited": True}, "Only infrastructure can expedite"),
    ],
)
async def test_rejects_invalid_requests(client, auth, sent_mail, overrides, message):
    resp = await client.post("/api/mailinglist", json=request(**overrides), headers=auth("pmc"))
    data = await resp.get_json()
    assert data["success"] is False
    assert message in data["message"]
    assert not os.listdir(config.storage.queue_dir)
    assert not sent_mail


async def test_private_and_security_lists_must_be_private(client, auth):
    resp = await client.post(
        "/api/mailinglist", json=request(listpart="security", private=True), headers=auth("pmc")
    )
    assert (await resp.get_json())["success"] is True
    assert queued("mailinglist-security-httpd.apache.org.json")["private"] is True


async def test_root_can_use_any_domain_and_expedite(client, auth):
    now = int(time.time())
    resp = await client.post(
        "/api/mailinglist",
        json=request(domainpart="tomcat.apache.org", muopts="MU", expedited=True),
        headers=auth("root"),
    )
    assert (await resp.get_json())["success"] is True
    payload = queued("mailinglist-commits-tomcat.apache.org.json")
    assert payload["expedited"] is True
    assert payload["requested"] <= now - 86400 + 5  # expedited requests are back-dated a day
