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

from . import config
import asfpy.messaging
import os
import requests

"""Simple lib for sending emails based on templates"""

# Grab whimsy's mail mappings
WHIMSY_PUBDATA = requests.get("https://whimsy.apache.org/public/committee-info.json").json()["committees"]


def from_template(template_filename: str, recipient: str, variables: dict):
    template_path = os.path.join(config.messaging.template_dir, template_filename)
    assert os.path.isfile(template_path), f"Could not find template {template_path}"
    template_data = open(template_path).read()
    subject, body = template_data.split("--", maxsplit=1)
    asfpy.messaging.mail(
        sender=config.messaging.sender,
        recipient=recipient,
        subject=subject.strip().format(**variables),
        message=body.strip().format(**variables),
    )


def project_to_private(project: str):
    """Convert a project name to a private mailing list target"""
    if project in WHIMSY_PUBDATA:
        project = WHIMSY_PUBDATA[project].get("mail_list", project)
    return f"private@{project}.apache.org"
