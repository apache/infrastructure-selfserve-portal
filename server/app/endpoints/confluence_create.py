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
"""Handler for creating a confluence space"""

if not __debug__:
  raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import middleware, email, log
import asfquart
import asfquart.auth
from asfquart.auth import Requirements as R
import asfquart.session
import re
import asyncio

RE_VALID_SPACE = re.compile(r"^[A-Z0-9]+$")
ACLI_CMD = "/opt/latest-cli/acli.sh"

# Protected from archiving
PROTECTED_SPACES = (
    "INFRA",
    "INCUBATOR",
    "COMDEV",
)

CONFLUENCE_ERROR = "Confluence action failed due to an internal server error."
INVALID_NAME = "Invalid space name!"

async def confluence_user_exists(username: str):
    """Checks if a confluence user exists"""
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *("confluence", "--action", "getUser", "--userId", username, "--quiet"),
    )
    await proc.wait()
    assert proc.returncode == 0, "Could not find the specified administrator ID in confluence"


async def create_space(space: str, description: str):
    """Creates a new, blank confluence space"""
    assert RE_VALID_SPACE.match(space), INVALID_NAME
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "-v",
            "--action",
            "addSpace",
            "--space",
            space,
            "--description",
            description,
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, "Could not create new space, it may already exist"


async def set_default_space_access(space: str, admin: str):
    """Sets up default permissions for a space"""
    assert RE_VALID_SPACE.match(space), INVALID_NAME
    assert isinstance(admin, str) and admin, "Please specify a valid admin user"

    # All permissions for admin
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "--action",
            "addPermissions",
            "--permissions",
            "@all",
            "--space",
            space,
            "--userId",
            admin,
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, CONFLUENCE_ERROR

    # Anonymous read access
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "--action",
            "addPermissions",
            "--permissions",
            "VIEWSPACE",
            "--space",
            space,
            "--userId",
            "Anonymous",
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, CONFLUENCE_ERROR

    # View+export rights for logged-in users
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "--action",
            "addPermissions",
            "--permissions",
            "VIEWSPACE,EXPORTSPACE",
            "--space",
            space,
            "--group",
            "confluence-users",
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, CONFLUENCE_ERROR

    # Remove infrabot, tut tut
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "--action",
            "removePermissions",
            "--permissions",
            "@all",
            "--space",
            space,
            "--userId",
            "infrabot",
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, CONFLUENCE_ERROR


@asfquart.APP.route(
    "/api/confluence-create",
    methods=[
        "GET",
        "POST",  # Create a new confluence space
    ],
)
@asfquart.auth.require(any_of={R.member, R.chair})
async def process():
    sesion = await asfquart.session.read()
    form_data = await asfquart.utils.formdata()

    # Create a confluence space
    spacename = form_data.get("space")
    admin = form_data.get("admin")
    description = form_data.get("description")

    try:
        assert isinstance(spacename, str) and RE_VALID_SPACE.match(spacename), "Invalid space name specified"
        assert (
            isinstance(admin, str) and admin
        ), "Please specify a user to set as initial administrator of the new space"
        assert isinstance(description, str) and description, "Please write a short description of this new space"
        await confluence_user_exists(admin)
        await create_space(spacename, description)
        await set_default_space_access(spacename, admin)
    except AssertionError as e:
        return {"success": False, "message": str(e)}

    # Notify
    await log.slack(
        f"A new confluence space, `{spacename}`, has been created as requested by {session.uid}@apache.org."
    )

    email.from_template(
        "confluence_created.txt",
        recipient=("private@infra.apache.org", f"{session.uid}@apache.org"),
        variables={
            "spacename": spacename,
            "requester": session.uid,
        },
    )

    # All done for now
    return {
        "success": True,
        "message": "Confluence space created",
    }


