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
"""Handler for adding a user to an existing DockerHub group in the Apache org"""

if not __debug__:
    raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import config, log
from ..lib.dockerhub import get_token, auth_headers, DOCKERHUB_API
import asfquart
import asfquart.auth
import asfquart.session
import aiohttp
import re

VALID_GROUP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
VALID_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,100}$")


@asfquart.APP.route(
    "/api/dockerhub-add-user-to-group",
    methods=[
        "POST",  # Add a user to an existing DockerHub group
    ],
)
@asfquart.auth.require
async def process_dockerhub_add_user_to_group():
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()

    user = form_data.get("user")
    group = form_data.get("group")

    try:
        assert session.isRoot, "Only infrastructure team members may modify DockerHub group membership"
        assert isinstance(user, str) and VALID_USERNAME_RE.match(user), \
            "Invalid DockerHub username. Must only contain letters, digits, hyphens, underscores, or periods"
        assert isinstance(group, str) and VALID_GROUP_NAME_RE.match(group), \
            "Invalid group name. Must start with a lowercase letter or digit and only contain " \
            "lowercase letters, digits, hyphens, underscores, or periods"

        token = await get_token()
        headers = auth_headers(token)
        org = config.dockerhub.org

        async with aiohttp.ClientSession() as client:
            resp = await client.post(
                f"{DOCKERHUB_API}/orgs/{org}/groups/{group}/members",
                json={"member": user},
                headers=headers,
            )
            assert resp.status in (200, 201), \
                f"Failed to add user '{user}' to group '{group}': {await resp.text()}"

    except AssertionError as e:
        return {"success": False, "message": str(e)}

    await log.slack(
        f"DockerHub user `{user}` has been added to group `{group}` in the `{config.dockerhub.org}` org, "
        f"as requested by {session.uid}@apache.org."
    )

    return {
        "success": True,
        "message": f"User '{user}' added to group '{group}'.",
    }
