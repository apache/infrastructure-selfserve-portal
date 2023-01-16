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
import asyncio

"""Configuration classes for the platform"""

import yaml
import os
from . import log
import uuid
import asfpy.clitools


CONFIG_FILE = "config.yaml"


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
        self.error_reporting = yml.get("error_reporting", "json")
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


class LDAPConfiguration:
    def __init__(self, yml: dict):
        assert yml, f"No LDAP configuration directives could be found in {CONFIG_FILE}!"
        self.uri = yml["uri"]
        self.groupbase = yml["groupbase"]
        self.userbase = yml["userbase"]
        self.ldapbase = yml["ldapbase"]
        self.servicebase = yml["servicebase"]


class StorageConfiguration:
    def __init__(self, yml: dict):
        assert yml, f"No storage configuration directives could be found in {CONFIG_FILE}!"
        self.queue_dir = yml["queue_dir"]
        if not os.path.isdir(self.queue_dir):
            log.log(f"Queue directory {self.queue_dir} does not exist, will attempt to create it")
            os.makedirs(self.queue_dir, exist_ok=True, mode=0o700)


async def get_projects_from_ldap():
    """Reads and sets the current list of projects from LDAP"""
    ldap_search_timeout = 30  # Wait no more than 30 sec for ldap data...
    while True:
        ldap_base = ldap.groupbase.replace("cn=%s,", "")
        try:
            ldap_data = await asyncio.wait_for(asfpy.clitools.ldapsearch_cli_async(ldap_base, "children", "cn=*"), ldap_search_timeout)
            if ldap_data and len(ldap_data) > 100:
                project_list = set([x["cn"][0] for x in ldap_data])
            projects.clear()
            projects.extend(sorted(project_list))

        except asyncio.exceptions.TimeoutError:
            print("LDAP lookup for list of projects timed out, retrying in 10 minutes")
        await asyncio.sleep(600)


cfg_yaml = yaml.safe_load(open(CONFIG_FILE, "r"))
server = ServerConfiguration(cfg_yaml.get("server", {}))
ldap = LDAPConfiguration(cfg_yaml.get("ldap", {}))
storage = StorageConfiguration(cfg_yaml.get("storage", {}))
projects = []  # Filled every 10 min by get_projects_from_ldap
