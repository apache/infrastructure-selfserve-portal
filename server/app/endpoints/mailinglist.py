#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Selfserve Portal for the Apache Software Foundation"""
"""Handler for mailing list creation"""

if not __debug__:
    raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import middleware, config, asfuid, email, log
import asfquart
import asfquart.auth
import asfquart.session
from asfquart.auth import Requirements as R
import time
import json
import os
import re

VALID_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
VALID_LISTPART_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# These lists are accepted as private (and MUST be private). All other lists should be public unless root.
PRIVATE_LISTS = (
    "private",
    "security",
)
# Valid moderator options that ezmlm-make accepts
VALID_MUOPTS = ("mu", "Mu", "mU")
VALID_MUOPTS_INFRA = ("mu", "mU", "Mu", "MU")  # Infra can use MU as well

# List parts cannot end in -default or -owner
INVALID_ENDINGS = ( "-default", "-owner", )


def can_manage_domain(session, domain: str):
    """Yields true if the user can manage a specific project domain, otherwise False"""
    if session.isRoot is True:  # Root can always manage
        return True
    for project in session.committees:
        if config.messaging.mail_mappings.get(project) == domain:
            return True
    return False


@asfquart.APP.route(
    "/api/mailinglist",
    methods=[
        "POST",  # Create a new mailing list
    ],
)
@asfquart.auth.require({R.pmc_member})
async def process_lists():
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()
    # Creating a new mailing list

    listpart = form_data.get("listpart")
    domainpart = form_data.get("domainpart")
    moderators = form_data.get("moderators")
    is_private = form_data.get("private", False)
    muopts = form_data.get("muopts")
    trailer = form_data.get("trailer", False)
    expedited = form_data.get("expedited")
    now = int(time.time())
    # Validate data
    try:
        assert listpart and VALID_LISTPART_RE.match(
            listpart
        ), "Invalid list name. Must only consist of alphanumerical characters and dashes"
        assert listpart.endswith("-digest") is False, "A mailing list cannot end in -digest"
        assert domainpart in config.messaging.mail_mappings.values(), "Mailing list domain is not a valid ASF hostname"
        assert can_manage_domain(session, domainpart), "You are not authorized to create mailing lists for this domain"
        assert isinstance(moderators, list) and moderators, "You need to provide a list of moderators"
        assert all(
            VALID_EMAIL_RE.match(moderator) for moderator in moderators
        ), "Invalid moderator list provided. Please use valid email addresses only"
        assert not is_private or (
            listpart in PRIVATE_LISTS or session.isRoot is True
        ), "Only private@ or security@ can be made private by default. Please file a ticket with Infrastructure for non-standard private lists"
        assert is_private or listpart not in PRIVATE_LISTS, "private@ and security@ lists MUST be marked as private"
        assert muopts in VALID_MUOPTS or (session.isRoot is True and muopts in VALID_MUOPTS_INFRA), "Invalid moderation options given"
        assert isinstance(trailer, bool), "Trailer option must be a boolean value"
        assert not expedited or session.isRoot, "Only infrastructure can expedite mailing list requests"
        assert f"{listpart}@{domainpart}" not in config.messaging.mailing_lists, "This mailing already exists"
        assert not any(listpart.endswith(bad_ending) for bad_ending in INVALID_ENDINGS), "Invalid list name. Cannot end in a restricted ezmlm keyword"
    except AssertionError as e:
        return {"success": False, "message": str(e)}

    # This filename is also the ID of the request.
    filename = f"mailinglist-{listpart}-{domainpart}.json"

    # Generate the payload for mailreq
    request_time = now
    if expedited:  # If expedited request, for backwards compat, we pretend it came in a day earlier.
        request_time -= 86400
    payload = {
        "type": "mailinglist",
        "id": filename,
        "requester": session.uid,
        "requested": request_time,
        "domain": domainpart,
        "list": listpart,
        "muopts": muopts,
        "private": is_private,
        "mods": moderators,
        "trailer": "t" if trailer else "T",
        "expedited": expedited,
    }

    # Save payload file
    filepath = os.path.join(config.storage.queue_dir, filename)
    with open(filepath, "w") as f:
        json.dump(payload, f)

    # Notify of pending request
    visitype = "private" if is_private else "public"
    await log.slack(
        f"A new {visitype} mailing list, `{listpart}@{domainpart}` has been queued for creation, as requested by {session.uid}@apache.org."
    )

    email.from_template(
        "mailinglist_create.txt",
        recipient=("private@infra.apache.org", f"{session.uid}@apache.org"),
        variables={
            "listpart": listpart,
            "domainpart": domainpart,
            "requester": session.uid,
        },
    )

    # All done for now
    return {
        "success": True,
        "message": "Request logged. Please allow for up to 24 hours for the request to be processed.",
    }
