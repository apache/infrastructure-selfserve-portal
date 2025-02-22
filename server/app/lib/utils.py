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

import re

VALID_EMAIL_LOCAL = re.compile(r"\S+") # local-part can be anything non-spaces
VALID_EMAIL_DOMAIN = re.compile(r"\S+") # domain ditto currently (but maybe restrict to alphanumeric?)
VALID_USERNAME_RE = re.compile(r"[a-z][a-z0-9]{3,20}")  # 4-20 lowercase alphanumeric, starting with alpha
VALID_USERNAME_MSG = '4-20 lowercase alphanumeric, starting with alpha'

# validate an email address
def check_email_address(email: str) -> bool:
    parts = email.split('@')
    if len(parts) != 2: # must have just one '@'
        return False
    local, domain = parts
    return VALID_EMAIL_LOCAL.fullmatch(local) and len(domain.split('.')) > 1 and VALID_EMAIL_DOMAIN.fullmatch(domain)

# generic user id check; OK for JIRA and CONFLENCE (and ASF ids)
def check_user_id_syntax(uid: str) -> bool:
    return VALID_USERNAME_RE.fullmatch(uid)

# same as above currently
def check_confluence_id_syntax(uid: str) -> bool:
    return check_user_id_syntax(uid)

# same as above currently
def check_jira_id_syntax(uid: str) -> bool:
    return check_user_id_syntax(uid)
