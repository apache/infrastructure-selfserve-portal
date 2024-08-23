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
"""Handler for jira account creation"""

if not __debug__:
  raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import middleware, config, email
import asfquart
import asfquart.auth
from asfquart.auth import Requirements as R
import asfquart.session
import quart
import uuid
import time
import asfpy.sqlite
import os
import re
import asyncio
import aiohttp

NOTIFICATION_TARGET = "notifications@infra.apache.org"  # This is to notify infra as well as projects about pending requests

# infra-reports' more extensive userid search which includes user IDs that are not necessarily present in crowd but would cause issues.
INFRAREPORTS_USERID_CHECK = "https://infra-reports.apache.org/api/userid"

VALID_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
VALID_JIRA_USERNAME_RE = re.compile(r"^[^<>&%\s]{4,20}$")  # 4-20 chars, no whitespace or illegal chars
# Taken from com.atlassian.jira.bc.user.UserValidationHelper

# It is expensive to use the Jira CLI to check for existing user ids
# This table is pre-populated with existing ids and the app adds new ids on creation
JIRA_CREATE_USERS_STATEMENT = """
CREATE TABLE IF NOT EXISTS users (
     userid text COLLATE NOCASE PRIMARY KEY
    );
"""

# This table holds pending requests
# The validated column can have the values:
# - 0: email has not yet been validated
# - 1: email has been validated, and email sent to PMC
# The entry is deleted when the request is approved, or 24 hours after it has been denied if so (denied_ts timestamp)
JIRA_CREATE_PENDING_STATEMENT = """
CREATE TABLE IF NOT EXISTS pending (
     userid text COLLATE NOCASE PRIMARY KEY,
     token text NOT NULL,
     realname text NOT NULL,
     email text NOT NULL,
     project text NOT NULL,
     why text NOT NULL,
     created integer NOT NULL,
     userip text NOT NULL,
     validated integer NOT NULL,
     denied_ts integer DEFAULT 0
    );
"""

# Table for blocked projects (no Jira accounts should be made for them)
JIRA_CREATE_BLOCKED_STATEMENT = """
CREATE TABLE IF NOT EXISTS blocked (
     project text COLLATE NOCASE PRIMARY KEY
    );
"""

JIRA_USER_DB = os.path.join(config.storage.db_dir, "jira.db")

JIRA_DB = asfpy.sqlite.db(JIRA_USER_DB)

# Log file for ACLI operations
JIRA_ACLI_LOG = os.path.join(config.storage.db_dir, "acli.log")

# Prefixes used the distinguish user and pmc threads
# include 'jiraaccount-' as well to avoid possible clash with other modules
JIRA_USER_THREAD_PREFIX = 'jiraaccount-user'
JIRA_PMC_THREAD_PREFIX = 'jiraaccount-pmc'

if not JIRA_DB.table_exists("users"):
    print("Creating Jira users database")
    JIRA_DB.runc(JIRA_CREATE_USERS_STATEMENT)


if not JIRA_DB.table_exists("pending"):
    print("Creating Jira pending database")
    JIRA_DB.runc(JIRA_CREATE_PENDING_STATEMENT)

if not JIRA_DB.table_exists("blocked"):
    print("Creating Jira blocked projects database")
    JIRA_DB.runc(JIRA_CREATE_BLOCKED_STATEMENT)


async def prune_stale_requests():
    """Runs through pending requests, removing them if stale"""
    while True:  # Loop, sleep for two hours when done processing
        pending_requests = list([x for x in JIRA_DB.fetch("pending", limit=1000)])  # Fetch up to 1000 docs at once
        now = int(time.time())
        for req in pending_requests:
            if req["denied_ts"] and req["denied_ts"] < (now-86400):  # denied, 24 hours elapsed, delete!
                print(f"Removing stale account request {req['token']} - denied >24h ago")
                JIRA_DB.delete("pending", token=req["token"])
            elif req["created"] < (now-86400*90):  # Too old (> 90 days), delete
                print(f"Removing stale account request {req['token']} - created >90d ago")
                JIRA_DB.delete("pending", token=req["token"])
        await asyncio.sleep(7200)  # Sleep for two hours, why not



@asfquart.APP.route(
    "/api/jira-exists",
    methods=[
        "GET",
    ],
)
async def check_user_exists_jira():
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()
    """Checks if a username has already been taken"""
    userid = form_data.get("userid")
    if userid and JIRA_DB.fetchone("users", userid=userid):
        return {"found": True}
    else:
        # INFRA-25324: Check infra-reports' userid db as well, but only if we couldn't the userid locally
        async with aiohttp.ClientSession() as client:
            async with client.get(INFRAREPORTS_USERID_CHECK, params={"id": userid}) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return {"found": result.get("exists", True)}  # Default to True if the backend throws a gnome at us.
                else:
                    return {"success": False, "message": "Your query could not be completed at this point. Please retry later."}


@asfquart.APP.route(
    "/api/jira-project-blocked",
    methods=[
        "POST",
    ],
)
async def check_project_blocked_jira():
    """Checks if a project is 'blocked', meaning it doesn't use JIRA"""
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()
    project = form_data.get("project")
    if project and JIRA_DB.fetchone("blocked", project=project):
        return {"blocked": True}
    else:
        return {"blocked": False}


@asfquart.APP.route(
    "/api/jira-account",
    methods=[
        "GET",  # Token verification (email validation)
        "POST",  # User submits request
    ],
)
async def process_jiraaccount():
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()
    # Submit application
    if quart.request.method == "POST":
        desired_username = form_data.get("username")
        real_name = form_data.get("realname")
        email_address = form_data.get("email")
        contact_project = form_data.get("project")
        why = form_data.get("why")
        userip = quart.request.remote_addr
        now = int(time.time())

        # Validate fields
        try:
            assert (
                isinstance(desired_username, str) and len(desired_username) >= 4
            ), "Jira Username should at least be four character long"
            assert VALID_JIRA_USERNAME_RE.match(
                desired_username
            ), "Your Jira username contains invalid characters, or is too long"
            assert (
                isinstance(real_name, str) and len(real_name) >= 3
            ), "Your public (real) name must be at least three characters long"
            assert isinstance(email_address, str) and VALID_EMAIL_RE.match(
                email_address
            ), "Please enter a valid email address"
            assert (
                isinstance(contact_project, str) and contact_project in config.projects
            ), "Please select a valid project"
            # Ensure the project isn't blocking jira account creations
            assert (
                    JIRA_DB.fetchone("blocked", project=contact_project) is None
            ), "The project you have selected does not use Jira for issue tracking. Please contact the project to find out where to submit issues."
            assert (
                isinstance(why, str) and len(why) > 10
            ), "Please write a valid reason why you want a Jira account. Make sure it contains enough information for reviewers to properly assess your request."

            # Check that username ain't taken
            assert (
                JIRA_DB.fetchone("users", userid=desired_username) is None
            ), "The username you selected is already in use"
            assert (
                JIRA_DB.fetchone("pending", userid=desired_username) is None
            ), "The username you selected is already in use"

            # Check that the requester does not already have a pending request
            assert (
                JIRA_DB.fetchone("pending", email=email_address) is None
            ), "There is already a pending Jira account request associated with this email address. Please wait for it to be processed"

        except AssertionError as e:
            return {"success": False, "message": str(e)}

        # Save the pending request
        token = str(uuid.uuid4())
        JIRA_DB.insert(
            "pending",
            {
                "userid": desired_username,
                "token": token,
                "email": email_address,
                "realname": real_name,
                "project": contact_project,
                "why": why,
                "created": now,
                "userip": userip,
                "validated": 0,
            },
        )

        # Send the verification email
        verify_url = f"https://{asfquart.app.request.host}/jira-account-verify.html?{token}"
        email.from_template("jira_account_verify.txt",
                            recipient=email_address,
                            variables={"verify_url": verify_url},
                            thread_start=True, thread_key=f"{JIRA_USER_THREAD_PREFIX}-{token}"
                            )

        # All done for now
        return {
            "success": True,
            "message": "Request logged. Please verify your email address",
        }

    # Validate email
    elif quart.request.method == "GET":
        token = form_data.get("token")
        record = JIRA_DB.fetchone("pending", token=token)
        if record and record["validated"] == 0:  # Valid, not-already-validated token?
            # Set validated to true
            JIRA_DB.update("pending", {"validated": 1}, token=token)

            # Notify project
            record["review_url"] = f"https://{asfquart.app.request.host}/jira-account-review.html?token={token}"
            project_private_list = email.project_to_private(record["project"])
            email.from_template("jira_account_pending_review.txt",
                                recipient=[NOTIFICATION_TARGET, project_private_list],
                                variables=record,
                                thread_start=True, thread_key=f"{JIRA_PMC_THREAD_PREFIX}-{token}"
                                )

            return {"success": True, "message": "Your email address has been validated.", "ppl": project_private_list}
        else:
            return {"success": False, "message": "Unknown or already validated token sent."}

@asfquart.APP.route(
    "/api/jira-account-review",
    methods=[
        "GET",  # View account request
        "POST",  # Action account request (approve/deny)
    ],
)
@asfquart.auth.require
async def process_review():
    """Review and/or approve/deny a request for a new jira account"""
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()
    try:
        token = form_data.get("token")  # Must have a valid token
        assert isinstance(token, str) and len(token) == 36, "Invalid token format"
        entry = JIRA_DB.fetchone("pending", token=token)  # Fetch request entry from DB, verify it
        assert entry, "Could not find the pending account request. It may have already been reviewed."
        assert entry["validated"] == 1, "This Jira account request has not been verified by the requester yet."
        # Only project committers (and infra) can review requests for a project
        assert (
            entry["project"] in session.projects or session.isRoot
        ), "You can only review account requests related to the projects you are on"
    except AssertionError as e:
        return {"success": False, "message": str(e)}

    # Review application
    if quart.request.method == "GET":
        public_keys = (
            "created",
            "project",
            "userid",
            "realname",
            "userip",
            "why",
        )
        public_entry = {k: entry[k] for k in public_keys}
        return {"success": True, "entry": public_entry}

    # Approve/deny application
    if quart.request.method == "POST":
        action = form_data.get("action")
        if action == "approve":
            try:
                acli_arguments = (
                    "jira",
                    "-v", # for debugging (output goes to a journal)
                    "--action",
                    "addUser",
                    "--userId",
                    entry["userid"],
                    "--userFullName",
                    entry["realname"],
                    "--userEmail",
                    entry["email"],
                )
                proc = await asyncio.create_subprocess_exec(
                    "/opt/latest-cli/acli.sh",
                    *acli_arguments,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                # Log things for debug purposes
                with open(JIRA_ACLI_LOG, "a") as aclilog:
                    aclilog.write(f"Ran ACLI with arguments: {' '.join(acli_arguments)}\n")
                    aclilog.write(f"Process returned code {proc.returncode}\n")
                    aclilog.write(f"stdout was: \n{stdout.decode()}\n")
                    aclilog.write(f"stderr was: \n{stderr.decode()}\n")
                    aclilog.write(f"---------------------------------------------\n\n")
                # Check for known error messages in stderr:
                assert b"A user with that username already exists" not in stderr, "An account with this username already exists in Jira"
                assert not re.search(b"Client error: User '.+?' is already defined.", stderr or b""), "The Jira backend was unable to create this account due to a naming conflict. Please contact infrastructure and have them create the account."
                # Check that call was okay (exit code 0)
                assert proc.returncode == 0, "Jira account creation failed due to an internal server error."
            except (AssertionError, FileNotFoundError) as e:
                return {"success": False, "message": str(e)}

            # Remove entry from pending db, append username to list of active jira users
            JIRA_DB.delete("pending", token=token)
            JIRA_DB.insert("users", {"userid": entry["userid"]})

            # Send welcome email
            email.from_template("jira_account_welcome.txt",
                                recipient=entry["email"],
                                variables=entry,
                                thread_start=False, thread_key=f"{JIRA_USER_THREAD_PREFIX}-{token}"
                                )

            # Notify project via private list
            private_list = email.project_to_private(entry["project"])
            entry["approver"] = session.uid
            email.from_template("jira_account_welcome_pmc.txt",
                                recipient=[NOTIFICATION_TARGET, private_list ],
                                variables=entry,
                                thread_start=False, thread_key=f"{JIRA_PMC_THREAD_PREFIX}-{token}"
                                )

            return {"success": True, "message": "Account created, welcome email has been dispatched."}

        elif action == "deny":
            if entry.get("denied_ts", 0):  # If already denied, the denied_ts entry is > 0. Only deny once
              return {"success": False, "message": "This account request has already been denied. Nothing to do."}
            entry["denied_ts"] = int(time.time())  # Mark when denied, for db pruning loop
            JIRA_DB.update("pending", entry, token=entry["token"])

            # Add optional reason for denying
            entry["reason"] = form_data.get("reason") or "No reason given."

            # Inform requester
            email.from_template("jira_account_denied.txt",
                                recipient=entry["email"],
                                variables=entry,
                                thread_start=False, thread_key=f"{JIRA_USER_THREAD_PREFIX}-{token}"
                                )
            # Notify project via private list
            private_list = email.project_to_private(entry["project"])
            entry["approver"] = session.uid
            email.from_template("jira_account_denied_pmc.txt",
                                recipient=[NOTIFICATION_TARGET, private_list ],
                                variables=entry,
                                thread_start=False, thread_key=f"{JIRA_PMC_THREAD_PREFIX}-{token}"
                                )

            return {"success": True, "message": "Account denied, notification dispatched."}

# Add background loop for pruning pending requests db
asfquart.APP.add_background_task(prune_stale_requests)
