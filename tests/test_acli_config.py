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

"""Tests that Jira and Confluence acli operations can be configured with, and use,
independent acli binaries/versions (see AcliConfiguration in server/app/lib/config.py)."""

import asyncio
import importlib.util
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO_ROOT, "server")


def _write_config_yaml(directory, acli_yaml=""):
    """Writes a minimal-but-complete config.yaml, with storage dirs pointed at `directory`"""
    queue_dir = os.path.join(directory, "queue")
    db_dir = os.path.join(directory, "db")
    config_contents = f"""
server:
  bind: 127.0.0.1
  port: 8000
ldap:
  uri: ldaps://example.org:636
  userbase: uid=%s,ou=people,dc=example,dc=org
  groupbase: cn=%s,ou=project,ou=groups,dc=example,dc=org
  servicebase: cn=%s,ou=groups,ou=services,dc=example,dc=org
  ldapbase: dc=example,dc=org
storage:
  queue_dir: "{queue_dir}"
  db_dir: "{db_dir}"
messaging:
  sender: "test <test@example.org>"
  template_dir: "{directory}"
{acli_yaml}
"""
    with open(os.path.join(directory, "config.yaml"), "w") as f:
        f.write(config_contents)


def _clear_app_modules():
    """Drops cached `app.*` modules, so config.py's module-level code re-runs on next import"""
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def _import_endpoint(module_name):
    """Imports a single app/endpoints/<module_name>.py directly, bypassing app/endpoints/__init__.py
    (which eagerly imports every endpoint module, including ones that need a real database)."""
    path = os.path.join(SERVER_DIR, "app", "endpoints", f"{module_name}.py")
    full_name = f"app.endpoints.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def acli_config(tmp_path, monkeypatch):
    """Returns a factory that (re)loads app.lib.config against a temp config.yaml with the
    given acli: yaml block, and returns the freshly loaded config module."""

    def _load(acli_yaml=""):
        _write_config_yaml(tmp_path, acli_yaml)
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(SERVER_DIR)
        _clear_app_modules()
        import asfquart

        asfquart.construct("test_selfserve", oauth="/api/auth")  # Needed before endpoints can register routes
        from app.lib import config

        return config

    yield _load
    _clear_app_modules()


def test_acli_defaults_to_shared_binary_when_unconfigured(acli_config):
    """No acli: section in config.yaml -> both products keep using the historical shared path"""
    config = acli_config()
    assert config.acli.jira_cmd == "/opt/latest-cli/acli.sh"
    assert config.acli.confluence_cmd == "/opt/latest-cli/acli.sh"


def test_acli_jira_and_confluence_can_use_independent_binaries(acli_config):
    """An acli: section can point Jira and Confluence at two different acli installs"""
    config = acli_config(
        'acli:\n'
        '  jira_cmd: "/opt/acli-jira-v9/acli.sh"\n'
        '  confluence_cmd: "/opt/acli-confluence-v8/acli.sh"\n'
    )
    assert config.acli.jira_cmd == "/opt/acli-jira-v9/acli.sh"
    assert config.acli.confluence_cmd == "/opt/acli-confluence-v8/acli.sh"
    assert config.acli.jira_cmd != config.acli.confluence_cmd


def test_jira_and_confluence_endpoints_invoke_their_own_configured_acli(acli_config):
    """The actual subprocess call each endpoint module makes should use its own configured acli binary"""
    acli_config(
        'acli:\n'
        '  jira_cmd: "/opt/acli-jira-v9/acli.sh"\n'
        '  confluence_cmd: "/opt/acli-confluence-v8/acli.sh"\n'
    )
    jira_create = _import_endpoint("jira_create")
    confluence_create = _import_endpoint("confluence_create")

    fake_proc = AsyncMock()
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)) as mock_exec:
        asyncio.run(jira_create.jira_user_exists("someuser"))
        jira_binary = mock_exec.call_args[0][0]

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake_proc)) as mock_exec:
        asyncio.run(confluence_create.confluence_user_exists("someuser"))
        confluence_binary = mock_exec.call_args[0][0]

    assert jira_binary == "/opt/acli-jira-v9/acli.sh"
    assert confluence_binary == "/opt/acli-confluence-v8/acli.sh"
    assert jira_binary != confluence_binary
