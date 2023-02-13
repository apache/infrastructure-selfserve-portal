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
"""generic logging for the portal"""

import asfpy.syslog
import aiohttp
from . import config

log = asfpy.syslog.Printer(stdout=True, identity="selfserve-platform")


async def slack(message: str):
    """Logs a message to #asfinfra in slack"""
    # Incoming webhook style
    if config.messaging.slack_url:
        async with aiohttp.ClientSession() as client:
            await client.post(config.messaging.slack_url, json={"text": message})
    # Token style
    elif config.messaging.slack_token and config.messaging.slack_channel:
        async with aiohttp.ClientSession() as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {config.messaging.slack_token}"},
                json={"channel": config.messaging.slack_channel, "text": message},
            )
    # Nothing defined? just print
    else:
        print(message)
