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
"""Handler for creating a DockerHub repository and associating an existing group with it"""

if not __debug__:
    raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import config, log
from ..lib.dockerhub import get_token, auth_headers, DOCKERHUB_API
import asfquart
import asfquart.auth
import asfquart.session
import aiohttp
import re

# Docker Hub repository names: lowercase letters, digits, underscores, periods, hyphens.
# Must begin with a letter or digit.
VALID_REPO_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,98}$")
# Group (team) names follow the same general pattern
VALID_GROUP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@asfquart.APP.route(
    "/api/dockerhub-add-repository",
    methods=[
        "POST",  # Create a new DockerHub repository and associate a group with it
    ],
)
@asfquart.auth.require
async def process_dockerhub_add_repository():
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()

    repository = form_data.get("repository")
    summary = form_data.get("summary", "")
    description = form_data.get("description", "")
    group = form_data.get("group")

    try:
        assert session.isRoot, "Only infrastructure team members may create DockerHub repositories"
        assert isinstance(repository, str) and VALID_REPO_NAME_RE.match(repository), \
            "Invalid repository name. Must start with a lowercase letter or digit and only contain " \
            "lowercase letters, digits, hyphens, underscores, or periods (max 100 characters)"
        assert isinstance(group, str) and VALID_GROUP_NAME_RE.match(group), \
            "Please specify a valid, existing DockerHub group name to associate with the repository"

        token = await get_token()
        headers = auth_headers(token)
        org = config.dockerhub.org

        async with aiohttp.ClientSession() as client:
            # Create the repository in the org
            payload = {
                "description": summary,
                "full_description": description,
                "is_private": False,
                "name": repository,
                "namespace": org,
            }
            resp = await client.post(f"{DOCKERHUB_API}/repositories/", json=payload, headers=headers)
            data = await resp.json()
            assert resp.status == 201, \
                f"Failed to create repository '{repository}': {data.get('message', str(data))}"

            # Fetch the group ID so we can reference it when granting access
            resp = await client.get(f"{DOCKERHUB_API}/orgs/{org}/groups/{group}", headers=headers)
            group_data = await resp.json()
            assert resp.status == 200, \
                f"Could not find group '{group}': {group_data.get('message', str(group_data))}"
            group_id = group_data["id"]

            # Grant the group write access to the new repository
            resp = await client.post(
                f"{DOCKERHUB_API}/repositories/{org}/{repository}/groups",
                json={"group_id": group_id, "permission": "write"},
                headers=headers,
            )
            assert resp.status in (200, 201), \
                f"Failed to add group '{group}' to repository '{repository}': {await resp.text()}"

    except AssertionError as e:
        return {"success": False, "message": str(e)}

    await log.slack(
        f"A new DockerHub repository `{config.dockerhub.org}/{repository}` has been created "
        f"and group `{group}` has been granted write access, as requested by {session.uid}@apache.org."
    )

    return {
        "success": True,
        "message": f"Repository '{repository}' created and group '{group}' granted write access.",
    }
