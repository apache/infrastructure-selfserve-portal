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
"""Handler for archiving a confluence space"""

if not __debug__:
    raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import middleware, email, log
import asfquart
import asfquart.session
import asfquart.auth
import json
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

async def set_archived_status(space: str):
    """Mark a confluence space as archived"""
    assert RE_VALID_SPACE.match(space), INVALID_NAME
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "-v",
            "--action",
            "updateSpace",
            "--options",
            "status=archived",
            "--space",
            space,
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, CONFLUENCE_ERROR


async def get_space_owners(space: str):
    """Gets the list of users and groups with access to a confluence space"""
    assert RE_VALID_SPACE.match(space), INVALID_NAME
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "--action",
            "getSpacePermissionList",
            "--outputType",
            "json",
            "--space",
            space,
            "--quiet",
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await proc.communicate()
    assert stdout, "Could not find this confluence space"
    js = json.loads(stdout)
    users = set()
    groups = set()
    for entry in js:
        if entry["idType"] == "user":
            users.add(entry["id"])
        elif entry["idType"] == "group":
            groups.add(entry["id"])
    await proc.wait()
    assert proc.returncode == 0, CONFLUENCE_ERROR
    return users, groups


async def remove_space_access(space: str, userlist=None, grouplist=None):
    """Removes space access to a list of one or more users"""
    assert RE_VALID_SPACE.match(space), INVALID_NAME
    if userlist:
        if isinstance(userlist, list) or isinstance(userlist, set):
            userlist = ",".join(userlist)
        assert isinstance(userlist, str), "Userlist must be a string or list of strings"
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
                userlist,
            ),
        )
        await proc.wait()
        assert proc.returncode == 0, CONFLUENCE_ERROR
    if grouplist:
        if isinstance(grouplist, list) or isinstance(grouplist, set):
            grouplist = ",".join(grouplist)
        assert isinstance(grouplist, str), "Grouplist must be a string or list of strings"
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
                "--group",
                grouplist,
            ),
        )
        await proc.wait()
        assert proc.returncode == 0, CONFLUENCE_ERROR


async def read_only_access(space: str):
    """Adds read-only access to a space"""
    assert RE_VALID_SPACE.match(space), INVALID_NAME
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
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, _stderr = await proc.communicate()
    assert proc.returncode == 0, CONFLUENCE_ERROR

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
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, _stderr = await proc.communicate()
    assert proc.returncode == 0, CONFLUENCE_ERROR


@asfquart.auth.require(any_of={asfquart.auth.Requirements.member, asfquart.auth.Requirements.chair})
async def process(form_data):
    # Archive a confluence space
    spacename = form_data.get("space")
    session = await asfquart.session.read()
    try:
        assert isinstance(spacename, str) and RE_VALID_SPACE.match(spacename), "Invalid space name specified"
        assert spacename not in PROTECTED_SPACES, "You cannot archive this confluence space"
        users, groups = await get_space_owners(spacename)
        await set_archived_status(spacename)
        await remove_space_access(spacename, userlist=users, grouplist=groups)
        await read_only_access(spacename)
    except AssertionError as e:
        return {"success": False, "message": str(e)}

    # Notify
    await log.slack(
        f"The confluence space, `{spacename}`, has been archived as read-only, as requested by {session.uid}@apache.org."
    )

    email.from_template(
        "confluence_archived.txt",
        recipient=("private@infra.apache.org", f"{session.uid}@apache.org"),
        variables={
            "spacename": spacename,
            "requester": session.uid,
        },
    )

    # All done for now
    return {
        "success": True,
        "message": "Confluence space archived",
    }


asfquart.APP.add_url_rule(
    "/api/confluence-archive",
    methods=[
        "POST",  # Archive a space
    ],
    view_func=middleware.glued(process),
)
