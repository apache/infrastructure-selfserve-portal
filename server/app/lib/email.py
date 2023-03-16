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

from . import config
import asfpy.messaging
import os

"""Simple lib for sending emails based on templates"""

# If a domain/project cannot be found, we redirect mail to infra
DEFAULT_MAIL_HOST = "infra.apache.org"


def from_template(template_filename: str, recipient: str, variables: dict, thread_start: bool=False, thread_key: str=None):
    """generate and send email from template"""
    template_path = os.path.join(config.messaging.template_dir, template_filename)
    assert os.path.isfile(template_path), f"Could not find template {template_path}"
    template_data = open(template_path).read()
    subject, body = template_data.split("--", maxsplit=1)
    asfpy.messaging.mail(
        sender=config.messaging.sender,
        recipient=recipient,
        subject=subject.strip().format(**variables),
        message=body.strip().format(**variables),
        thread_start=thread_start,
        thread_key=thread_key,
        headers={},
    )


def project_to_private(project: str):
    """Convert a project name to a private mailing list target"""
    project_hostname = config.messaging.mail_mappings.get(project)
    if not project_hostname:  # If hostname wasn't found, alert private@infra instead.
        project_hostname = DEFAULT_MAIL_HOST
    return f"private@{project_hostname}"
