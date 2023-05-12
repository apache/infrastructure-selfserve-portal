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
import re
import asyncio
import psycopg

ONE_DAY = 86400  # A day in seconds

VALID_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
VALID_JIRA_USERNAME_RE = re.compile(r"^[^<>&%\s]{4,20}$")  # 4-20 chars, no whitespace or illegal chars
# Taken from com.atlassian.jira.bc.user.UserValidationHelper

# Jira PSQL DSN
JIRA_PGSQL_DSN = psycopg.conninfo.make_conninfo(**config.jirapsql.yaml)

# Mappings dict for userid<->email
JIRA_EMAIL_MAPPINGS = {}


async def update_jira_email_map():
    """Updates the jira userid<->email mappings from psql on a daily basis"""
    while True:
        print("Updating Jira email mappings dict")
        try:
            tmp_dict = {}
            async with await psycopg.AsyncConnection.connect(JIRA_PGSQL_DSN) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT lower_user_name, email_address from cwd_user WHERE directory_id != 10000"
                    )
                    async for row in cur:
                        tmp_dict[row[0]] = row[1]

            # Clear and refresh mappings
            JIRA_EMAIL_MAPPINGS.clear()
            JIRA_EMAIL_MAPPINGS.update(tmp_dict)
        except psycopg.OperationalError as e:
            print(f"Operational error while querying Jira PSQL: {e}")
            print("Retrying later...")
        await asyncio.sleep(ONE_DAY)  # Wait a day...


@middleware.rate_limited
async def process(formdata):
    jira_username = formdata.get("username")
    jira_email = formdata.get("email")
    if jira_username and jira_username in JIRA_EMAIL_MAPPINGS:
        if JIRA_EMAIL_MAPPINGS[jira_username] == jira_email:
            return {"found": True}
    return {"found": False}


quart.current_app.add_url_rule(
    "/api/jira-account-activate",
    methods=[
        "GET",  # DEBUG
        "POST",  # Account re-activation request from user
    ],
    view_func=middleware.glued(process),
)

# Schedule background updater of email mappings
quart.current_app.add_background_task(update_jira_email_map)
