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
"""Shared DockerHub API helpers for the ASF Selfserve Portal"""

if not __debug__:
    raise RuntimeError("This code requires assert statements to be enabled")

import aiohttp
from . import config

DOCKERHUB_API = "https://hub.docker.com/v2"


async def get_token() -> str:
    """Authenticate to DockerHub using configured credentials and return a bearer token."""
    assert config.dockerhub.username and config.dockerhub.password, \
        "DockerHub credentials are not configured. Please add a 'dockerhub' section to config.yaml."
    async with aiohttp.ClientSession() as client:
        resp = await client.post(
            f"{DOCKERHUB_API}/users/login",
            json={"username": config.dockerhub.username, "password": config.dockerhub.password},
        )
        data = await resp.json()
        assert resp.status == 200, f"Failed to authenticate to DockerHub: {data.get('detail', str(data))}"
        return data["token"]


def auth_headers(token: str) -> dict:
    """Return standard DockerHub auth headers for a given bearer token."""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
