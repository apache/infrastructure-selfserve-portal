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
import pyotp
from . import config

DOCKERHUB_API = "https://hub.docker.com/v2"


async def get_token() -> str:
    """Authenticate to DockerHub and return a bearer token.

    If the account has 2FA enabled, set totp_secret in config.yaml to the
    base32 seed shown when the authenticator app was first configured.
    get_token() will then automatically perform the two-step login:
      1. POST /v2/users/login  -> returns login_2fa_token
      2. POST /v2/users/2fa-login with a live TOTP code -> returns bearer token
    """
    assert config.dockerhub.username and config.dockerhub.secret, \
        "DockerHub credentials are not configured. Please add a 'dockerhub' section to config.yaml."

    async with aiohttp.ClientSession() as client:
        # Step 1: initial login with username + PAT
        resp = await client.post(
            f"{DOCKERHUB_API}/users/login",
            json={"username": config.dockerhub.username, "password": config.dockerhub.secret},
        )
        assert resp.status == 200, \
            f"DockerHub login failed ({resp.status}): {await resp.text()}"
        data = await resp.json(content_type=None)  # content_type=None avoids mimetype errors

        # Step 2: if the account has 2FA enabled, DockerHub returns login_2fa_token
        # instead of the final bearer token, and we must complete a second call.
        if "login_2fa_token" in data:
            assert config.dockerhub.totp_secret, \
                "DockerHub returned a 2FA challenge but no totp_secret is configured in config.yaml. " \
                "Set totp_secret to the base32 seed from your authenticator app setup."
            totp_code = pyotp.TOTP(config.dockerhub.totp_secret).now()
            resp = await client.post(
                f"{DOCKERHUB_API}/users/2fa-login",
                json={"login_2fa_token": data["login_2fa_token"], "code": totp_code},
            )
            assert resp.status == 200, \
                f"DockerHub 2FA login failed ({resp.status}): {await resp.text()}"
            data = await resp.json(content_type=None)

        assert "token" in data, f"DockerHub login response did not contain a token: {data}"
        return data["token"]


def auth_headers(token: str) -> dict:
    """Return standard DockerHub auth headers for a given bearer token."""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
