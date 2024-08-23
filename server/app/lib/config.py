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
"""SelfServe Platform for the Apache Software Foundation"""

if not __debug__:
  raise RuntimeError("This code requires assert statements to be enabled")

import asyncio


"""Configuration classes for the platform"""

import yaml
import os
from . import log
import uuid
import asfpy.clitools
import aiohttp
import json

# If pipservice, we may use the pipservice module to define a config. Use if found.
PIPSERVICE_CONFIG = os.path.join(os.path.realpath(".."), "selfserve-portal.yaml")
CONFIG_FILE = PIPSERVICE_CONFIG if os.path.isfile(PIPSERVICE_CONFIG) else "config.yaml"
WEBMOD_MAILING_LIST_URL = "https://webmod.apache.org/lists"
WHIMSY_COMMITTEE_URL = "https://whimsy.apache.org/public/committee-info.json"

# The two mail domain bases - apache.org for the foundation, apachecon.com for apachecon
BASE_MAIL_DOMAINS = {
    "foundation": "apache.org",
    "apachecon": "apachecon.com",
}


def text_to_int(size):
    """Convert shorthand size notation to integer (kb,mb,gb)"""
    if isinstance(size, int):
        return size
    assert isinstance(size, str), "Byte size must be either integer or string value!"
    if size.endswith("kb"):
        return int(size[:-2]) * 1024
    elif size.endswith("mb"):
        return int(size[:-2]) * 1024 * 1024
    elif size.endswith("gb"):
        return int(size[:-2]) * 1024 * 1024 * 1024
    else:
        return int(size)


class ServerConfiguration:
    def __init__(self, yml: dict):
        assert yml, f"No server configuration directives could be found in {CONFIG_FILE}!"
        self.bind = yml["bind"]
        self.port = int(yml["port"])
        self.error_reporting = yml.get("error_reporting", "show")
        self.upload_timeout = int(yml.get("upload_timeout", 3600))
        self.debug_mode = bool(yml.get("debug_mode", False))
        self.debug_user = yml.get("debug_user", "testuser")
        self.debug_password = yml.get("debug_password")
        if not self.debug_password:
            self.debug_password = str(uuid.uuid4())[:8]
        if self.debug_mode is True:
            log.log("Debug mode enabled:")
            log.log(f"Debug username: {self.debug_user}")
            log.log(f"Debug password: {self.debug_password}")
        self.max_form_size = text_to_int(yml.get("max_form_size", "100mb"))
        assert self.max_form_size >= 1024, "Max form size needs to be at least 1kb!"
        self.max_content_length = int(self.max_form_size * 1.34)  # Max plus b64 overhead
        self.rate_limit_per_ip = int(yml.get("rate_limit_per_ip", 0))


class LDAPConfiguration:
    def __init__(self, yml: dict):
        assert yml, f"No LDAP configuration directives could be found in {CONFIG_FILE}!"
        self.uri = yml["uri"]
        self.groupbase = yml["groupbase"]
        self.userbase = yml["userbase"]
        self.ldapbase = yml["ldapbase"]
        self.servicebase = yml["servicebase"]
        self.roleaccounts = {}
        # API role accounts for external services in a file
        # user:pwd, one per line, use # for comment lines
        ra_path = yml.get("roleaccounts")
        if ra_path and os.path.isfile(ra_path):
            with open(ra_path) as f:
                for line in f.readlines():
                    if ":" in line and not line.startswith("#"):
                        user, pwd = line.strip().split(":", 1)
                        self.roleaccounts[user] = pwd


class StorageConfiguration:
    def __init__(self, yml: dict):
        assert yml, f"No storage configuration directives could be found in {CONFIG_FILE}!"
        self.queue_dir = yml["queue_dir"]
        if not os.path.isdir(self.queue_dir):
            log.log(f"Queue directory {self.queue_dir} does not exist, will attempt to create it")
            os.makedirs(self.queue_dir, exist_ok=True, mode=0o700)
        self.db_dir = yml["db_dir"]
        if not os.path.isdir(self.db_dir):
            log.log(f"Database directory {self.db_dir} does not exist, will attempt to create it")
            os.makedirs(self.db_dir, exist_ok=True, mode=0o700)


class MessagingConfiguration:
    def __init__(self, yml: dict):
        self.sender = yml["sender"]
        self.template_dir = yml["template_dir"]
        self.mailing_lists = []
        self.mail_mappings = {}
        self.slack_url = yml.get("slack_url")  # Incoming webhook style
        self.slack_token = yml.get("slack_token")  # restricted token style
        self.slack_channel = yml.get("slack_channel")  # token style, cont'd.


class JiraPSQLConfiguration:
    def __init__(self, yml: dict):
        if yml:
            # TODO: More verbosity here. We only need the raw dict to pass to the DSN constructor.
            assert all(key in yml for key in ("host", "user", "password", "dbname",)), "Jira PSQL config is missing information!"
            self.yaml = yml

class CwikiMySQLConfiguration:
    def __init__(self, yml: dict):
        if yml:
            # TODO: More verbosity here. We only need the raw dict to pass to the DSN constructor.
            assert all(key in yml for key in ("host", "user", "password", "dbname",)), "Cwiki MySQL config is missing information!"
            yml["db"] = yml["dbname"]  # Renaming internally due to API, but keeping it conforming externally
            del yml["dbname"]
            self.yaml = yml


async def get_projects_from_ldap():
    """Reads and sets the current list of projects from LDAP"""
    ldap_search_timeout = 30  # Wait no more than 30 sec for ldap data...
    while True:
        ldap_base = ldap.groupbase.replace("cn=%s,", "")
        try:
            ldap_data = await asyncio.wait_for(
                asfpy.clitools.ldapsearch_cli_async(ldap_base, "children", "cn=*"), ldap_search_timeout
            )
            if ldap_data and len(ldap_data) > 100:
                project_list = set([x["cn"][0] for x in ldap_data])
            projects.clear()
            project_list.add("infra")  # Add infra for testing
            projects.extend(sorted(project_list))
            # Grab the mailing list hostname mappings for our projects
            await fetch_committee_mappings()
        except asyncio.exceptions.TimeoutError:
            print("LDAP lookup for list of projects timed out, retrying in 10 minutes")
        await asyncio.sleep(600)


async def fetch_valid_lists():
    """Fetches the current list of active mailing lists"""
    while True:
        async with aiohttp.ClientSession() as client:
            async with client.get(WEBMOD_MAILING_LIST_URL) as resp:
                if resp.status == 200:
                    try:
                        messaging.mailing_lists = await resp.json()
                    except json.JSONDecodeError as e:
                        print(f"Could not decode JSON from webmod: {e}")
                else:
                    txt = await resp.text()
                    print(f"Could not fetch mailing lists from webmod.apache.org: {txt}")
        await asyncio.sleep(3600)  # Wait an hour


async def fetch_committee_mappings():
    """Fetches the committee info from Whimsy, in order to create project-to-hostname mappings"""
    async with aiohttp.ClientSession() as client:
        async with client.get(WHIMSY_COMMITTEE_URL) as resp:
            if resp.status == 200:
                try:
                    committee_json = await resp.json()
                    if "committees" in committee_json:
                        committees = committee_json["committees"]
                        mail_mappings = BASE_MAIL_DOMAINS.copy()
                        for project in projects:
                            if project in committees:
                                project_domain = committees[project].get("mail_list", project)
                            else:
                                project_domain = project
                            mail_mappings[project] = f"{project_domain}.apache.org"
                        messaging.mail_mappings = mail_mappings
                except json.JSONDecodeError as e:
                    print(f"Could not decode JSON from whimsy: {e}")
            else:
                txt = await resp.text()
                print(f"Could not fetch committee info from whimsy.apache.org: {txt}")

cfg_yaml = yaml.safe_load(open(CONFIG_FILE, "r"))
server = ServerConfiguration(cfg_yaml.get("server", {}))
ldap = LDAPConfiguration(cfg_yaml.get("ldap", {}))
storage = StorageConfiguration(cfg_yaml.get("storage", {}))
messaging = MessagingConfiguration(cfg_yaml.get("messaging", {}))
jirapsql = JiraPSQLConfiguration(cfg_yaml.get("jirapsql", {}))
cwikimysql = CwikiMySQLConfiguration(cfg_yaml.get("cwikimysql", {}))
projects = []  # Filled every 10 min by get_projects_from_ldap
rate_limits = {}  # Tracks IPs and their usage, resets every day
