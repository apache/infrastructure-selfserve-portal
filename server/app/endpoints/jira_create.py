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
"""Handler for creating a jira project"""

if not __debug__:
  raise RuntimeError("This code requires assert statements to be enabled")

from ..lib import middleware, asfuid, email, log, config
import asfquart
import re
import asyncio
import os
import json

RE_VALID_PROJECT_KEY = re.compile(r"^[A-Z0-9]+$")
ACLI_CMD = "/opt/latest-cli/acli.sh"
JIRA_SCHEME_FILES = {
    "workflow": "/x1/acli/site/js/jiraworkflowschemes.json",
}


async def jira_user_exists(username: str):
    """Checks if a jira user exists"""
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *("jira", "--action", "getUser", "--userId", username, "--quiet"),
    )
    await proc.wait()
    assert proc.returncode == 0, "Could not find the specified project lead ID in Jira"


async def create_jira_project(
    project_key: str,
    project_name: str,
    description: str,
    project_lead: str,
    issue_scheme: str,
    workflow_scheme: str,
    homepage_url: str,
):
    """Creates a new jira project"""
    assert RE_VALID_PROJECT_KEY.match(project_key), "Invalid project key!"
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "jira",
            "-v",
            "--action",
            "createProject",
            "--project",
            project_key,
            "--name",
            project_name,
            "--description",
            description,
            "--lead",
            project_lead,
            "--issueTypeScheme",
            issue_scheme,
            "--workflowScheme",
            workflow_scheme,
            "--url",
            homepage_url,
            "--notificationScheme",
            "Empty Scheme",
            "--permissionScheme",
            "_Default Permission Scheme_",
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, "Could not create new jira project, it may already exist"


async def set_project_access(project_key: str, ldap_project: str):
    """Sets up default permissions for a project"""
    assert RE_VALID_PROJECT_KEY.match(project_key), "Invalid space name!"
    assert (
        isinstance(ldap_project, str) and ldap_project and ldap_project in config.projects
    ), "Please specify a valid PMC"

    # Admin access for PMC
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "jira",
            "--action",
            "addProjectRoleActors",
            "--project",
            project_key,
            "--role",
            "administrators",
            "--group",
            f"{ldap_project}-pmc",
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, f"Could not assign administrator access to {ldap_project}-pmc"

    # Standard access to project committers
    proc = await asyncio.create_subprocess_exec(
        ACLI_CMD,
        *(
            "jira",
            "--action",
            "addProjectRoleActors",
            "--project",
            project_key,
            "--role",
            "committers",
            "--group",
            ldap_project,
        ),
    )
    await proc.wait()
    assert proc.returncode == 0, f"Could not assign write access to {ldap_project} committers"


@asfuid.session_required
async def process(form_data, session):
    # Create a new jira project

    project_key = form_data.get("project_key")
    project_name = form_data.get("project_name")
    project_lead = form_data.get("project_lead")
    ldap_project = form_data.get("ldap_project")
    issue_scheme = form_data.get("issue_scheme")
    workflow_scheme = form_data.get("workflow_scheme")
    homepage_url = form_data.get("homepage_url")
    description = form_data.get("description")

    try:
        assert (session.pmcs or session.root), "Only members of a (P)PMC may create jira projects"
        assert isinstance(project_key, str) and RE_VALID_PROJECT_KEY.match(project_key), "Invalid project key specified"
        assert isinstance(project_name, str) and project_name, "Please specify a title for the new Jira project"
        assert isinstance(description, str) and description, "Please write a short description of this new project"
        assert isinstance(project_lead, str) and project_lead, "Please specify a project lead for this project"
        assert (
            ldap_project in config.projects
        ), "Please specify a valid, current apache project to assign this Jira project to"
        if not session.root:
            assert ldap_project in session.pmcs, "You can only create a Jira project for an Apache project you are on the PMC of"
        assert isinstance(issue_scheme, str) and issue_scheme, "Please specify a valid issue scheme this project"
        assert (
            isinstance(workflow_scheme, str) and workflow_scheme
        ), "Please specify a valid workflow scheme for this project"
        assert isinstance(homepage_url, str) and homepage_url, "Please specify a homepage URL for this project"

        # Make sure project lead exists in Jira
        await jira_user_exists(project_lead)

        # Set up the new project
        await create_jira_project(
            project_key=project_key,
            project_name=project_name,
            project_lead=project_lead,
            description=description,
            issue_scheme=issue_scheme,
            workflow_scheme=workflow_scheme,
            homepage_url=homepage_url,
        )
        # Set standard access: admin for PMC, read/write for committers
        await set_project_access(project_key, ldap_project)

    except AssertionError as e:
        return {"success": False, "message": str(e)}

    # Notify
    await log.slack(f"A new Jira project, `{project_key}`, has been created as requested by {session.uid}@apache.org.")

    project_email = email.project_to_private(ldap_project)
    email.from_template(
        "jira_project_created.txt",
        recipient=("private@infra.apache.org", project_email, f"{session.uid}@apache.org"),
        variables={
            "project_key": project_key,
            "ldap_project": ldap_project,
            "requester": session.uid,
        },
    )

    # All done for now
    return {
        "success": True,
        "message": "Jira project created",
    }

@asfuid.session_required
async def list_schemes(form_data, session):
    """Lists current valid schemes for Jira"""
    scheme_dict = {}
    for key, filepath in JIRA_SCHEME_FILES.items():
        if os.path.isfile(filepath):
            try:
                js = json.load(open(filepath))
                scheme_dict[key] = js
            except json.JSONDecodeError:  # Bad JSON file? :/
                scheme_dict[key] = {}
    return asfquart.jsonify(scheme_dict)


asfquart.APP.add_url_rule(
    "/api/jira-project-create",
    methods=[
        "POST",  # Create a new jira project
    ],
    view_func=middleware.glued(process),
)


asfquart.APP.add_url_rule(
    "/api/jira-project-schemes",
    methods=[
        "GET",  # List valid schemes
    ],
    view_func=middleware.glued(list_schemes),
)
