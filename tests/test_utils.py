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

import sys

sys.path.extend(('server/app/lib',))

# import pytest

import utils

def mail_valid(email):
    assert utils.check_email_address(email), f"{email} should pass"
def mail_invalid(email):
    assert not utils.check_email_address(email), f"{email} should fail"

def uid_valid(uid):
    assert utils.check_user_id_syntax(uid), f"{uid} should pass"
def uid_invalid(uid):
    assert not utils.check_user_id_syntax(uid), f"{uid} should fail"

def test_email_validation():
    mail_valid('a@b.c')
    mail_valid('aZZZ@b.c.d.e.f')

    mail_invalid('a@bc')
    mail_invalid('a@b.c@d.e')

def test_uid_validation():
    uid_valid('abcd')
    uid_valid('a2345678901234567890')

    uid_invalid('0abc')
    uid_valid('a23456789012345678901')
