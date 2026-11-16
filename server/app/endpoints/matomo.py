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
"""Handler for requesting a new Matomo (web analytics) property"""

if not __debug__:
    raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import email, log, config
import asfquart
import asfquart.auth
import asfquart.session
import aiohttp
import asyncio
import html
import json
import re
import typing
import urllib.parse

# Free-text suffix for additional (non-main) sites, e.g. "Apache Zeppelin - Documentation"
RE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .\-]{0,39}$")
# Path segments allowed in a site URL, e.g. https://zeppelin.apache.org/docs
RE_URL_PATH = re.compile(r"^(/[A-Za-z0-9._~\-]+)*$")
MATOMO_TIMEOUT = 30  # seconds per API call
MATOMO_ERROR = "Matomo action failed due to an internal server error."

# Serialises the duplicate check and the creation, so two requests for one URL can't both succeed
CREATE_LOCK = asyncio.Lock()


class MatomoError(Exception):
    """A Matomo API call failed. The detail is logged for Infra, not shown to the requester."""


async def matomo_api(method: str, **params) -> typing.Any:
    """Calls a Matomo API method and returns its decoded JSON answer.

    The token is always POSTed (never in the query string), as Matomo recommends.
    """
    assert config.matomo.url and config.matomo.token, "Matomo is not configured"
    data = {
        "module": "API",
        "method": method,
        "format": "JSON",
        "token_auth": config.matomo.token,
        **params,
    }
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=MATOMO_TIMEOUT)) as client:
            async with client.post(f"{config.matomo.url}index.php", data=data) as resp:
                if resp.status != 200:
                    raise MatomoError(f"{method}: HTTP {resp.status}: {await resp.text()}")
                result = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
        raise MatomoError(f"{method}: {e!r}") from e
    if isinstance(result, dict) and result.get("result") == "error":
        raise MatomoError(f"{method}: {result.get('message')}")
    return result


def unwrap(result: typing.Any) -> typing.Any:
    """Matomo's JSON format wraps scalar answers as {"value": ...}"""
    if isinstance(result, dict) and "value" in result:
        return result["value"]
    return result


def project_domain(project: str) -> str:
    """The project's own apache.org hostname, e.g. zeppelin.apache.org"""
    return config.messaging.mail_mappings.get(project) or f"{project}.apache.org"


def project_site_name(project: str) -> str:
    """The Matomo name of a project's main site, e.g. "Apache Zeppelin" or "Apache HTTP Server"."""
    display_name = config.committee_names.get(project) or project.capitalize()
    if display_name.startswith("Apache "):
        return display_name
    return f"Apache {display_name}"


def normalise_site_url(url: str, domain: str) -> tuple[str, bool]:
    """Validates a requested site URL and returns (normalised URL, whether it is the project's main site).

    Sites must be served over https from the project's own domain or one of its subdomains,
    optionally under a path. Query strings, fragments, ports and credentials are refused.
    """
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        raise AssertionError("Please specify a valid site URL") from None
    hostname = (parsed.hostname or "").lower()
    assert parsed.scheme == "https" and hostname, "The site URL must start with https://"
    assert port is None and not parsed.username and not parsed.password, "Please specify a plain https:// site URL"
    assert not parsed.query and not parsed.fragment, "The site URL may not contain a query string or #fragment"
    assert hostname == domain or hostname.endswith(f".{domain}"), f"The site must be on {domain} or one of its subdomains"
    path = parsed.path.rstrip("/")
    assert RE_URL_PATH.match(path), "The site URL path may only contain letters, digits, '.', '_', '~' and '-'"
    is_main = hostname in (domain, f"www.{domain}") and not path
    return f"https://{hostname}{path}", is_main


def dashboard_url(site_id: int) -> str:
    return f"{config.matomo.url}index.php?module=CoreHome&action=index&idSite={site_id}&period=day&date=yesterday"


@asfquart.APP.route(
    "/api/matomo-site-create",
    methods=[
        "POST",  # Create a new Matomo property
    ],
)
@asfquart.auth.require
async def process_matomo_site_create():
    form_data = await asfquart.utils.formdata()
    session = await asfquart.session.read()

    project = form_data.get("project")
    url = form_data.get("url")
    label = (form_data.get("label") or "").strip()

    try:
        assert config.matomo.enabled, "Matomo property requests are not available at the moment. Please contact the Infrastructure team."
        assert (session.committees or session.isRoot), "Only members of a (P)PMC may request Matomo properties"
        assert isinstance(project, str) and project in config.projects, "Please specify a valid, current Apache project"
        if not session.isRoot:
            assert project in session.committees, "You can only request a Matomo property for an Apache project you are on the PMC of"
        assert isinstance(url, str) and url, "Please specify the URL of the site to track"
        site_url, is_main = normalise_site_url(url, project_domain(project))
        site_name = project_site_name(project)
        if not is_main:
            assert RE_LABEL.match(label), (
                "Sites other than the project's main website need a short label (e.g. 'Documentation'): "
                "up to 40 letters, digits, spaces, dots or dashes"
            )
            site_name = f"{site_name} - {label}"
    except AssertionError as e:
        return {"success": False, "message": str(e)}

    try:
        async with CREATE_LOCK:
            existing = await matomo_api("SitesManager.getSitesIdFromSiteUrl", url=site_url)
            if existing:
                ids = ", ".join(str(entry.get("idsite")) for entry in existing if isinstance(entry, dict))
                return {
                    "success": False,
                    "message": f"A Matomo property already exists for {site_url} (site ID {ids}). "
                    "Please contact the Infrastructure team if it needs changing.",
                }
            site_id = int(unwrap(await matomo_api("SitesManager.addSite", siteName=site_name, **{"urls[]": site_url})))
    except (MatomoError, TypeError, ValueError) as e:
        log.log(f"Matomo property creation for {site_url} ({project}) failed: {e}")
        return {"success": False, "message": MATOMO_ERROR}

    # The site exists from here on: later failures are reported to Infra, not returned as errors.
    problems = []
    if config.matomo.anonymous_view:
        try:
            await matomo_api("UsersManager.setUserAccess", userLogin="anonymous", access="view", idSites=site_id)
        except MatomoError as e:
            log.log(f"Could not grant anonymous view access to Matomo site {site_id}: {e}")
            problems.append("public (anonymous) view access could not be granted")

    tracking_code = None
    try:
        tracking_code = unwrap(await matomo_api("SitesManager.getJavascriptTag", idSite=site_id))
        assert isinstance(tracking_code, str) and tracking_code, "empty tracking code"
        if tracking_code.lstrip().startswith("&lt;"):  # Entity-encoded, if the JSON renderer didn't decode it
            tracking_code = html.unescape(tracking_code)
    except (MatomoError, AssertionError) as e:
        log.log(f"Could not fetch the tracking code for Matomo site {site_id}: {e}")
        problems.append("the tracking code could not be fetched")
        tracking_code = None

    # Notify
    message = (
        f"A new Matomo property, `{site_name}` (site ID {site_id}, {site_url}), "
        f"has been created as requested by {session.uid}@apache.org."
    )
    if problems:
        message += f" Needs attention: {'; '.join(problems)}."
    await log.slack(message)

    email.from_template(
        "matomo_site_created.txt",
        recipient=("private@infra.apache.org", email.project_to_private(project), f"{session.uid}@apache.org"),
        variables={
            "site_name": site_name,
            "site_id": site_id,
            "site_url": site_url,
            "project": project,
            "requester": session.uid,
            "dashboard_url": dashboard_url(site_id),
            "tracking_code": tracking_code
            or "(The tracking code could not be retrieved automatically. The Infrastructure team has been notified.)",
        },
    )

    return {
        "success": True,
        "message": f"Matomo property created with site ID {site_id}. "
        f"The details have also been sent to {email.project_to_private(project)}.",
        "site_id": site_id,
        "site_name": site_name,
        "site_url": site_url,
        "dashboard_url": dashboard_url(site_id),
        "tracking_code": tracking_code,
    }
