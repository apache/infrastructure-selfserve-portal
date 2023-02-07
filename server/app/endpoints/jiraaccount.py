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

from ..lib import middleware, config
import quart
import uuid
import time
import yaml
import asfpy.messaging
import asfpy.sqlite
import os
import re

VALID_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

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
            ), "Please write a valid reason why you need to create a Jira account"

            # Check that username ain't taken
            assert (
                JIRA_DB.fetchone("users", userid=desired_username) is None
            ), "The username you selected is already in use"
            assert (
                JIRA_DB.fetchone("pending", userid=desired_username) is None
            ), "The username you selected is already in use"
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
        asfpy.messaging.mail(
            sender=config.messaging.sender,
            recipient=email_address,
            subject="Please verify your email address",
            message=f"Bla bla bla, https://{quart.app.request.host}/jira-account.html?{token}",
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
        if record:  # Valid token?
            # Set validated to true
            JIRA_DB.update("pending", {"validated": 1}, token=token)

            # Notify project
            project = record["project"]
            userid = record["userid"]
            asfpy.messaging.mail(
                sender=config.messaging.sender,
                recipient=f"private@{project}.apache.org",
                subject="New Jira account requested: {userid}",
                message=f"Testing, testing, https://{quart.app.request.host}/jira-validate.html?{token}",
            )

            return {
                "success": True,
                "message": "bleep blorp"
            }
        else:
            return {
                "success": False,
                "message": "Blooorp :("
            }


app = quart.current_app


jira_process_middlewared = middleware.middleware(process)
jira_check_user_middlewared = middleware.middleware(check_user_exists)


@app.route(
    "/api/jira-account",
    methods=[
        "GET",     # Token verification (email validation)
        "POST",    # User submits request
        "PATCH",   # PMC verifying a request
        "DELETE",  # PMC denying a request
    ],
)
async def run_jiraaccount(**kwargs):
    return await jira_process_middlewared(**kwargs)


@app.route(
    "/api/jira-exists",
    methods=[
        "GET",
    ],
)
async def run_jira_check_user(**kwargs):
    return await jira_check_user_middlewared(**kwargs)
