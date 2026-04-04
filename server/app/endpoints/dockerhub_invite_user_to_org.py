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
"""Handler for inviting a user to the Apache DockerHub org (and optionally a group)"""

if not __debug__:
    raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import config, log
from ..lib.dockerhub import get_token, auth_headers
import asfquart
import asfquart.auth
import asfquart.session
import aiohttp
import re

VALID_GROUP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# Invitees can be a DockerHub username or an email address
VALID_INVITEE_RE = re.compile(r"^[a-zA-Z0-9._%+@-]{1,200}$")

DOCKERHUB_INVITES_URL = "https://hub.docker.com/v2/invites/bulk"


@asfquart.APP.route(
    "/api/dockerhub-invite-user-to-org",
    methods=[
        "POST",  # Invite a user to the Apache DockerHub org, optionally adding them to a group
    ],
)
@asfquart.auth.require
async def process_dockerhub_invite_user_to_org():
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()

    user = form_data.get("user")      # DockerHub username or email of the invitee
    group = form_data.get("group")    # Optional: existing group to place the user in upon acceptance

    try:
        assert session.isRoot, "Only infrastructure team members may invite users to the DockerHub org"
        assert isinstance(user, str) and VALID_INVITEE_RE.match(user), \
            "Invalid invitee. Please provide a valid DockerHub username or email address"
        assert group is None or (isinstance(group, str) and VALID_GROUP_NAME_RE.match(group)), \
            "Invalid group name. Must start with a lowercase letter or digit and only contain " \
            "lowercase letters, digits, hyphens, underscores, or periods"

        token = await get_token()
        headers = auth_headers(token)
        org = config.dockerhub.org

        invite_payload = {
            "org": org,
            "role": "member",
            "invitees": [user],
        }
        if group:
            invite_payload["team"] = group

        async with aiohttp.ClientSession() as client:
            resp = await client.post(DOCKERHUB_INVITES_URL, json=invite_payload, headers=headers)
            assert resp.status in (200, 201), \
                f"Failed to invite user '{user}' to the org: {await resp.text()}"

    except AssertionError as e:
        return {"success": False, "message": str(e)}

    group_msg = f" and added to group `{group}`" if group else ""
    await log.slack(
        f"DockerHub user `{user}` has been invited to the `{config.dockerhub.org}` org{group_msg}, "
        f"as requested by {session.uid}@apache.org."
    )

    group_info = f" and will be added to group '{group}' upon acceptance" if group else ""
    return {
        "success": True,
        "message": f"Invitation sent to '{user}'{group_info}.",
    }
