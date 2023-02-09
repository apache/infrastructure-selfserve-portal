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

from ..lib import middleware, config, asfuid, email
import quart
import uuid
import time
import asfpy.sqlite
import os
import re
import asyncio

VALID_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
VALID_JIRA_USERNAME_RE = re.compile(r"^[^<>&%\s]{4,20}$")  # 4-20 chars, no whitespace or illegal chars
# Taken from com.atlassian.jira.bc.user.UserValidationHelper

JIRA_CREATE_USERS_STATEMENT = """
CREATE TABLE IF NOT EXISTS users (
     userid text COLLATE NOCASE PRIMARY KEY
    );
"""
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
     validated integer NOT NULL
    );
"""

JIRA_USER_DB = os.path.join(config.storage.db_dir, "jira.db")

JIRA_DB = asfpy.sqlite.db(JIRA_USER_DB)


if not JIRA_DB.table_exists("users"):
    print(f"Creating Jira users database")
    JIRA_DB.runc(JIRA_CREATE_USERS_STATEMENT)


if not JIRA_DB.table_exists("pending"):
    print(f"Creating Jira pending database")
    JIRA_DB.runc(JIRA_CREATE_PENDING_STATEMENT)


async def check_user_exists(form_data):
    """Checks if a username has already been taken"""
    # Rate limited?
    if config.is_rate_limited(quart.request):
        return quart.Response(status=429, response="Your request has been rate-limited. Please check back tomorrow!")
    userid = form_data.get("userid")
    if userid and JIRA_DB.fetchone("users", userid=userid):
        return {"found": True}
    else:
        return {"found": False}


async def process(form_data):

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
            assert (
                isinstance(why, str) and len(why) > 10
            ), "Please write a valid reason why you need to create a Jira account. Make sure it contains enough information for reviewers to properly assess your request."

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
        verify_url = f"https://{quart.app.request.host}/jira-account-verify.html?{token}"
        email.from_template("jira_account_verify.txt", recipient=email_address, variables={"verify_url": verify_url})

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
            record["review_url"] = f"https://{quart.app.request.host}/jira-account-review.html?token={token}"
            email.from_template(
                "jira_account_pending_review.txt",
                recipient=email.project_to_private(record["project"]),
                variables=record,
            )

            return {"success": True, "message": "Your email address has been validated."}
        else:
            return {"success": False, "message": "Unknown or already validated token sent."}


@asfuid.session_required
async def process_review(form_data, session):
    """Review and/or approve/deny a request for a new jira account"""
    try:
        token = form_data.get("token")  # Must have a valid token
        assert isinstance(token, str) and len(token) == 36, "Invalid token format"
        entry = JIRA_DB.fetchone("pending", token=token)  # Fetch request entry from DB, verify it
        assert entry, "Could not find the pending account request. It may have already been reviewed."
        assert entry["validated"] == 1, "This Jira account request has not been verified by the requester yet."
        # Only project committers (and infra) can review requests for a project
        assert (
            entry["project"] in session.projects or session.root
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
                proc = await asyncio.create_subprocess_exec(
                    "/opt/latest-cli/acli.sh",
                    *(
                        "jira",
                        "-v",
                        "--action",
                        "addUser",
                        "--userId",
                        entry["userid"],
                        "--userFullName",
                        entry["realname"],
                        "--userEmail",
                        entry["email"],
                        "--continue",
                    ),
                )
                await proc.wait()
                assert proc.returncode == 0, "Jira account creation failed due to an internal server error."
            except (AssertionError, FileNotFoundError) as e:
                return {"success": False, "message": str(e)}

            # Remove entry from pending db, append username to list of active jira users
            JIRA_DB.delete("pending", token=token)
            JIRA_DB.insert("users", {"userid": entry["userid"]})

            # Send welcome email
            email.from_template("jira_account_welcome.txt", recipient=entry["email"], variables=entry)

            # Notify project via private list
            private_list = email.project_to_private(entry["project"])
            entry["approver"] = session.uid
            email.from_template("jira_account_welcome_pmc.txt", recipient=private_list, variables=entry)

            return {"success": True, "message": "Account created, welcome email has been dispatched."}

        elif action == "deny":
            # Remove entry from pending db
            JIRA_DB.delete("pending", token=token)

            # Add optional reason for denying
            entry["reason"] = form_data.get("reason") or "No reason given."

            # Inform requester
            email.from_template("jira_account_denied.txt", recipient=entry["email"], variables=entry)

            # Notify project via private list
            private_list = email.project_to_private(entry["project"])
            entry["approver"] = session.uid
            email.from_template("jira_account_denied_pmc.txt", recipient=private_list, variables=entry)

            return {"success": True, "message": "Account denied, notification dispatched."}


quart.current_app.add_url_rule(
    "/api/jira-account",
    methods=[
        "GET",  # Token verification (email validation)
        "POST",  # User submits request
    ],
    view_func=middleware.glued(process)
)
quart.current_app.add_url_rule(
    "/api/jira-exists",
    methods=[
        "GET",
    ],
    view_func=middleware.glued(check_user_exists)
)

quart.current_app.add_url_rule(
    "/api/jira-account-review",
    methods=[
        "GET",  # View account request
        "POST",  # Action account request (approve/deny)
    ],
    view_func=middleware.glued(process_review)
)
