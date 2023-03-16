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
"""Handler for queues for external services"""

if not __debug__:
  raise RuntimeError("This code requires assert statements to be enabled")

import quart
from ..lib import middleware, asfuid, config
import os
import json
import re

VALID_QUEUE_FILENAME = re.compile(r"^[-.a-z0-9]+\.json$")


@asfuid.session_required
async def list_queue(form_data, session):
    """Lists the current selfserve request queue, or removes an item that has been processed"""
    if not session.roleaccount:
        return {
            "success": False,
            "message": "This endpoint is only available to external services",
        }, 403
    # Externals can remove an item (mark it as processed) by using the `rm` key.
    to_remove = form_data.get("rm")
    if to_remove:
        assert VALID_QUEUE_FILENAME.match(to_remove)
        filepath = os.path.join(config.storage.queue_dir, to_remove)
        if os.path.isfile(filepath):
            os.unlink(filepath)
            return {"success": True, "message": "Item removed from queue"}
        else:
            return {"success": False, "message": "Item not found in queue"}, 404

    # If not removing an item, assume the service just wants to list the current queue
    queue_files = [filename for filename in os.listdir(config.storage.queue_dir) if filename.endswith(".json")]
    queue = []
    for queue_file in queue_files:
        filepath = os.path.join(config.storage.queue_dir, queue_file)
        try:
            js = json.load(open(filepath))
            queue.append(js)
        except json.JSONDecodeError:
            pass
    return quart.jsonify(queue)


quart.current_app.add_url_rule(
    "/api/queue",
    methods=[
        "GET",
    ],
    view_func=middleware.glued(list_queue),
)
