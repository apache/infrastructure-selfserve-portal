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
"""ASF User Information via LDAP or OAuth"""

from . import config
import re
import asfpy.aioldap
import quart
import time

UID_RE = re.compile(r"^(?:uid=)?([^,]+)")
SESSION_TIMEOUT = 86400  # Time out user sessions after 1 day.


class LDAPClient:
    def __init__(self, username: str, password: str):
        self.userid = username
        self.client = asfpy.aioldap.LDAPClient(config.ldap.uri, config.ldap.userbase % username, password)

    async def get_members(self, group: str):
        """Async fetching of members/owners of a standard project group."""
        ldap_base = config.ldap.groupbase % group
        members = []
        owners = []
        member_attr = "member"
        owner_attr = "owner"

        attrs = [member_attr, owner_attr]
        is_service_group = False
        async with self.client.connect() as conn:
            rv = await conn.search(ldap_base, attrs)
            if not rv:  # No such project - maybe a service?
                ldap_base = config.ldap.servicebase % group
                rv = await conn.search(ldap_base, attrs)
                is_service_group = True
            if not rv:
                raise Exception(f"No such LDAP group: {ldap_base}!")
            if member_attr in rv[0]:
                for member in sorted(rv[0][member_attr]):
                    m = UID_RE.match(member)
                    if m:
                        members.append(m.group(1))
            if owner_attr in rv[0]:
                for owner in sorted(rv[0][owner_attr]):
                    m = UID_RE.match(owner)
                    if m:
                        owners.append(m.group(1))
            if is_service_group and not owners:  # owners == members in service groups.
                owners = members
        return members, owners


async def membership(project: str):
    # Auth passed via Basic Auth header
    if quart.request.authorization and quart.request.authorization.username:
        if config.server.debug_mode is True and quart.request.authorization.username == config.server.debug_user:
            return True, True
        try:
            lc = LDAPClient(username=quart.request.authorization.username, password=quart.request.authorization.password)
            m, o = await lc.get_members(project)
            return lc.userid in m, lc.userid in o  # committer, pmc
        except asfpy.aioldap.errors.AuthenticationError as e:  # Auth error
            print(f"Auth error for {quart.request.authorization.username}: {e}")
        except Exception as e:  # Generic LDAP exception
            print(f"LDAP Exception for project {project}: {e}")
    # Auth passed via session cookie (OAuth)
    elif quart.session and "uid" in quart.session:
        if "projects" in quart.session and "pmcs" in quart.session:
            return project in quart.session["projects"], project in quart.session["pmcs"]
    return None, None  # Auth failure


class Credentials:
    """Get credentials of user via cookie or debug user (if debug enabled)"""

    def __init__(self):
        if quart.session and "uid" in quart.session:
            # Assert that the oauth session is not too old
            assert quart.session.get("timestamp", 0) > int(time.time() - SESSION_TIMEOUT), "Session timeout, please authenticate again"
            self.uid = quart.session["uid"]
            self.name = quart.session["fullname"]
            self.projects = quart.session["projects"]
            self.pmcs = quart.session["pmcs"]
            self.root = quart.session["isRoot"]

        elif (
            config.server.debug_mode is True
            and quart.request.authorization
            and quart.request.authorization.username == config.server.debug_user
            and quart.request.authorization.password == config.server.debug_password
        ):
            self.uid = "testing"
            self.name = "Test Account"
            self.projects = []
            self.pmcs = []
            self.root = True
        else:
            raise AssertionError("User not logged in via Web UI")
