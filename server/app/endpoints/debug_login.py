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
"""Development login, for testing the portal locally (e.g. in docker) without ASF OAuth.

Only active when server.debug_mode is true, and only for requests addressed to localhost.
Logins to /api/auth are then sent to a form here instead of to oauth.apache.org. The form takes
the debug password from the configuration, and lets the tester choose who to be: a user ID,
the (P)PMCs they are on, and whether they are root, a Foundation member or a chair.
"""

from ..lib import config, log
import asfquart
import asfquart.session
import html
import quart
import re
import secrets
import urllib.parse

DEBUG_LOGIN_URI = "/api/debug-login"
OAUTH_URI = "/api/auth"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
RE_UID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
RE_PROJECT = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

FORM = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Development login - ASF Self-serve Portal</title>
<link href="/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="container py-4" style="max-width: 640px;">
<h1>Development login</h1>
<div class="alert alert-warning">
    This portal runs in debug mode. This form replaces ASF OAuth and lets you log in as anyone.
    Debug mode must never be enabled in production.
</div>
{error}
<form method="post" action="{action}">
    <input type="hidden" name="login" value="{login}">
    <div class="mb-3">
        <label for="uid" class="form-label">User ID</label>
        <input required class="form-control" id="uid" name="uid" value="{uid}" pattern="[a-z0-9][a-z0-9._\\-]*">
    </div>
    <div class="mb-3">
        <label for="password" class="form-label">Debug password</label>
        <input required type="password" class="form-control" id="password" name="password" autofocus>
        <div class="form-text">server.debug_password in the configuration; the app also prints it at startup.</div>
    </div>
    <div class="mb-3">
        <label for="pmcs" class="form-label">(P)PMCs this user is on</label>
        <input class="form-control" id="pmcs" name="pmcs" value="{pmcs}" placeholder="e.g. aall, aamm">
        <div class="form-text">Comma-separated project names. The user is also a committer on each of them.</div>
    </div>
    <div class="mb-3">
        <div class="form-check"><input class="form-check-input" type="checkbox" id="root" name="root" value="1"><label class="form-check-label" for="root">Root (Infrastructure)</label></div>
        <div class="form-check"><input class="form-check-input" type="checkbox" id="member" name="member" value="1"><label class="form-check-label" for="member">Foundation member</label></div>
        <div class="form-check"><input class="form-check-input" type="checkbox" id="chair" name="chair" value="1"><label class="form-check-label" for="chair">PMC chair</label></div>
    </div>
    <button type="submit" class="btn btn-primary">Log in</button>
</form>
</body>
</html>
"""


def debug_login_allowed() -> bool:
    """Debug login needs debug mode, and a request addressed to this machine (not a public hostname)."""
    if not config.server.debug_mode:
        return False
    hostname = urllib.parse.urlsplit(f"//{quart.request.host}").hostname or ""
    return hostname in LOCAL_HOSTS


def safe_redirect(target: str) -> str:
    """Where to go after logging in: a path on this site. Anything pointing elsewhere becomes "/"."""
    parsed = urllib.parse.urlsplit(target or "")
    if parsed.scheme or parsed.netloc:  # Absolute URL: only accept this very site
        if parsed.scheme not in ("http", "https") or parsed.netloc != quart.request.host:
            return "/"
        target = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def render_form(login: str, uid: str = "", pmcs: str = "", error: str = "", status: int = 200):
    page = FORM.format(
        action=DEBUG_LOGIN_URI,
        login=html.escape(login),
        uid=html.escape(uid or config.server.debug_user),
        pmcs=html.escape(pmcs),
        error=f'<div class="alert alert-danger">{html.escape(error)}</div>' if error else "",
    )
    return quart.Response(page, status=status, content_type="text/html; charset=utf-8")


@asfquart.APP.before_request
async def divert_oauth_to_debug_login():
    """In debug mode, send OAuth logins (/api/auth?login=...) to the development login form instead."""
    if quart.request.path != OAUTH_URI or not debug_login_allowed():
        return None
    login_uri = quart.request.args.get("login")
    if login_uri is None and quart.request.query_string != b"login":
        return None  # Not a login: let asfquart handle logouts, callbacks and session lookups
    return quart.redirect(f"{DEBUG_LOGIN_URI}?{urllib.parse.urlencode({'login': login_uri or '/'})}")


@asfquart.APP.route(
    DEBUG_LOGIN_URI,
    methods=[
        "GET",  # Show the login form
        "POST",  # Log in
    ],
)
async def process_debug_login():
    if not debug_login_allowed():
        return quart.Response("Not found\n", status=404)

    if quart.request.method == "GET":
        return render_form(login=quart.request.args.get("login", "/"))

    form = await quart.request.form
    login = form.get("login", "/")
    uid = form.get("uid", "").strip().lower()
    pmc_text = form.get("pmcs", "")
    pmcs = sorted({name.strip().lower() for name in pmc_text.split(",") if name.strip()})

    if not secrets.compare_digest(form.get("password", "").encode(), str(config.server.debug_password).encode()):
        return render_form(login, uid, pmc_text, "Wrong debug password.", status=403)
    if not RE_UID.match(uid):
        return render_form(login, uid, pmc_text, "Please enter a valid user ID (lowercase letters, digits, '.', '_' or '-').", status=400)
    bad = [name for name in pmcs if not RE_PROJECT.match(name)]
    if bad:
        return render_form(login, uid, pmc_text, f"Invalid project name(s): {', '.join(bad)}", status=400)

    asfquart.session.write(
        {
            "uid": uid,
            "fullname": f"{uid} (debug login)",
            "email": f"{uid}@apache.org",
            "pmcs": pmcs,
            "projects": pmcs,
            "isRoot": form.get("root") == "1",
            "isMember": form.get("member") == "1",
            "isChair": form.get("chair") == "1",
        }
    )
    log.log(f"DEBUG LOGIN: {uid} logged in via the development login (pmcs={pmcs}, root={form.get('root') == '1'})")
    # Like asfquart's OAuth endpoint: a 200 with a Refresh header, so a SameSite session cookie survives the redirect
    target = safe_redirect(login)
    return quart.Response(
        f"Logged in as {uid} (debug login).\n",
        status=200,
        headers={"Refresh": f"0; url={target}"},
        content_type="text/plain; charset=utf-8",
    )
