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
import uuid

"""Handler for confluence account creation"""

from ..lib import config, email
import asfquart
import asfquart.utils
import re
import asyncio
import aiomysql

ONE_DAY = 86400  # A day in seconds

VALID_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
VALID_CONFLUENCE_USERNAME_RE = re.compile(r"^[^<>&%\s]{4,20}$")  # 4-20 chars, no whitespace or illegal chars
# Taken from com.atlassian.jira.bc.user.UserValidationHelper

# Mappings dict for userid<->email
CONFLUENCE_EMAIL_MAPPINGS = {}

# Reactivation queue. No real need for permanent storage here, all requests can be ephemeral.
CONFLUENCE_REACTIVATION_QUEUE = {}

# ACLI command - TODO: Add to yaml??
ACLI_CMD = "/opt/latest-cli/acli.sh"

APP = asfquart.APP


async def update_confluence_email_map():
    """Updates the confluence userid<->email mappings from mysql on a daily basis"""
    pool = await aiomysql.create_pool(**config.cwikimysql.yaml)
    while True:
        print("Updating Confluence email mappings dict")
        try:
            tmp_dict = {}
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT lower_user_name, email_address from cwd_user WHERE directory_id != 10000")
                    async for row in cur:
                        if all(x and isinstance(x, str) for x in row):  # Ensure we have actual (non-empty) strings here
                            tmp_dict[row[0]] = row[1]

            # Clear and refresh mappings
            CONFLUENCE_EMAIL_MAPPINGS.clear()
            CONFLUENCE_EMAIL_MAPPINGS.update(tmp_dict)
        except aiomysql.OperationalError as e:
            print(f"Operational error while querying Confluence MYSQL: {e}")
            print("Retrying later...")
        await asyncio.sleep(ONE_DAY)  # Wait a day...


async def activate_account(username: str):
    """Activates an account through ACLI"""
    email_address = CONFLUENCE_EMAIL_MAPPINGS[username]
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "confluence",
            "-v",
            "--action",
            "updateUser",
            "--userId",
            username,
            "--userEmail",
            email_address,
            "--activate",
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:  # If any errors show up in acli, bork
        # Test for ACLI whining but having done the job due to privacy redactions in Jira (email addresses being blank)
        good_bit = '"active":true'  # If the ACLI JSON output has this, it means the update worked, despite ACLI complaining.
        if good_bit in stdout or good_bit in stderr:
            return  # all good, ignore!
        print(f"Could not reactivate Confluence account '{username}': {stderr}")
        raise AssertionError("Confluence account reactivation failed due to an internal server error.")


@APP.route("/api/confluence-account-activate", methods=["GET", "POST"])
async def process_reactivation_request_cwiki():
    """Initial processing of an account re-activation request:
    - Check that username and email match
    - Send confirmation link to email address
    - Wait for confirmation...
    """
    formdata = await asfquart.utils.formdata()
    confluence_username = formdata.get("username")
    confluence_email = formdata.get("email")
    if confluence_email.lower().endswith("@apache.org"):  # This is LDAP operated, don't touch!
        return {"success": False, "message": "Reactivation of internal ASF accounts cannot be done through this tool."}
    if confluence_username and confluence_username in CONFLUENCE_EMAIL_MAPPINGS:
        if CONFLUENCE_EMAIL_MAPPINGS[confluence_username].lower() == confluence_email.lower():  # We have a match!
            # Generate and send confirmation link
            token = str(uuid.uuid4())
            verify_url = f"https://{APP.request.host}/confluence-account-reactivate.html?{token}"
            email.from_template(
                "confluence_account_reactivate.txt",
                recipient=confluence_email,
                variables={
                    "verify_url": verify_url,
                },
                thread_start=True,
                thread_key=f"confluence-activate-{token}",
            )
            # Store marker in our temp dict
            CONFLUENCE_REACTIVATION_QUEUE[token] = confluence_username
            return {"success": True}
    return {"success": False, "message": "We were unable to find the account based on the information provided. Either your Confluence account username, or the email address you registered it with, is incorrect."}


@APP.route("/api/confluence-account-activate-confirm", methods=["GET", "POST"])
async def process_confirm_reactivation_cwiki():
    """Processes confirmation link handling (and actual reactivation of an account)"""
    formdata = await asfquart.utils.formdata()
    token = formdata.get("token")
    if token and token in CONFLUENCE_REACTIVATION_QUEUE:  # Verify token
        username = CONFLUENCE_REACTIVATION_QUEUE[token]
        del CONFLUENCE_REACTIVATION_QUEUE[token]  # Remove right away, before entering the async wait
        if username in CONFLUENCE_EMAIL_MAPPINGS:
            try:
                await activate_account(username)
            except AssertionError as e:
                return {"success": False, "activated": False, "error": str(e)}
            return {"success": True, "activated": True}
    else:
        return {"success": False, "error": "Your token could not be found in our database. Please resubmit your request."}


# Schedule background updater of email mappings
APP.add_background_task(update_confluence_email_map)
