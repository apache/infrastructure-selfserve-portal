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

"""Personal Access Token handler for selfserve"""

import asfquart
import os

ROLEACCOUNT_FILE = os.path.normpath(os.path.join("..", "roleaccounts.txt"))


def load_roleaccounts(filepath: str) -> dict[str, str]:
    """Reads role accounts (name:token, one per line, # for comments) into a token -> name dict.
    Blank lines and lines without a colon are skipped."""
    accounts: dict[str, str] = {}
    if os.path.exists(filepath):
        print("Parsing role accounts list")
        with open(filepath, encoding="utf-8") as f:
            for line in f.readlines():
                if ":" in line and not line.startswith("#"):
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    print(f"Found role account: {k}")
                    accounts[v.strip()] = k
    return accounts


roleaccounts = load_roleaccounts(ROLEACCOUNT_FILE)


async def token_handler(token):
    if token in roleaccounts:
        return {
            "uid": roleaccounts[token],
            "fullname": f"{roleaccounts[token]} role Account",
            "roleaccount": True,
        }

asfquart.APP.token_handler = token_handler
