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

if not __debug__:
  raise RuntimeError("This code requires assert statements to be enabled")

from . import config
import re
import asfpy.aioldap
import asfquart
import time
import functools

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
    if asfquart.request.authorization and asfquart.request.authorization.username:
        if config.server.debug_mode is True and asfquart.request.authorization.username == config.server.debug_user:
            return True, True
        try:
            lc = LDAPClient(
                username=asfquart.request.authorization.username, password=asfquart.request.authorization.password
            )
            m, o = await lc.get_members(project)
            return lc.userid in m, lc.userid in o  # committer, pmc
        except asfpy.aioldap.errors.AuthenticationError as e:  # Auth error
            print(f"Auth error for {asfquart.request.authorization.username}: {e}")
        except Exception as e:  # Generic LDAP exception
            print(f"LDAP Exception for project {project}: {e}")
    # Auth passed via session cookie (OAuth)
    elif asfquart.session and "uid" in asfquart.session:
        if "projects" in asfquart.session and "pmcs" in asfquart.session:
            return project in asfquart.session["projects"], project in asfquart.session["pmcs"]
    return None, None  # Auth failure


class Credentials:
    """Get credentials of user via cookie or debug user (if debug enabled)"""

    def __init__(self):
        if asfquart.session and "uid" in asfquart.session:
            # Assert that the oauth session is not too old
            assert asfquart.session.get("timestamp", 0) > int(
                time.time() - SESSION_TIMEOUT
            ), "Session timeout, please authenticate again"
            self.uid = asfquart.session["uid"]
            self.name = asfquart.session["fullname"]
            self.projects = asfquart.session["projects"]
            self.pmcs = asfquart.session["pmcs"]
            self.root = bool(asfquart.session["isRoot"])
            self.member = bool(asfquart.session["isMember"])
            self.chair = bool(asfquart.session["isChair"])
            self.roleaccount = False

        elif (
            config.server.debug_mode is True
            and asfquart.request.authorization
            and asfquart.request.authorization.username == config.server.debug_user
            and asfquart.request.authorization.password == config.server.debug_password
        ):
            self.uid = "testing"
            self.name = "Test Account"
            self.projects = []
            self.pmcs = []
            self.root = True
            self.roleaccount = False
            self.member = False
            self.chair = False
        # Role account?
        elif asfquart.request.authorization:
            username = asfquart.request.authorization.username
            if (
                username in config.ldap.roleaccounts
                and config.ldap.roleaccounts[username] == asfquart.request.authorization.password
            ):
                self.uid = username
                self.name = "API Role Account"
                self.root = False
                self.member = False
                self.chair = False
                self.pmcs = []
                self.projects = []
                self.roleaccount = True
            else:
                raise AssertionError("Invalid authorization provided. If you are a committer, please log in via oauth")
        else:
            raise AssertionError("User not logged in via Web UI")


def session_required(func):
    """Decorator for calls that require the user to be authenticated against OAuth.
    Calls will be checked for an active, valid session, and if found, it will
    add the session to the list of arguments for the originator. Otherwise, it
    will return the standard no-auth JSON reply.
    Thus, calls that require a session can use:
    @asfuid.session_required
    async def foo(form_data, session):
      ...
    """

    @functools.wraps(func)
    async def session_wrapper(form_data):
        try:
            session = Credentials()  # Must be logged in via ASF OAuth
        except AssertionError as e:
            return {"success": False, "message": str(e)}, 403
        return await func(form_data, session)

    return session_wrapper
