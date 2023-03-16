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

if not __debug__:
  raise RuntimeError("This code requires assert statements to be enabled")

import sys
import traceback
import typing
import uuid
import quart
from . import config
import werkzeug.routing


async def consume_body():
    """Consumes the request body, punting it to dev-null. This is required for httpd to not throw 502 at error"""
    # See: https://bz.apache.org/bugzilla/show_bug.cgi?id=55433
    async for _data in quart.request.body:
        pass


def glued(func: typing.Callable) -> typing.Callable:
    """Middleware that collects all form data (except file uploads!) and joins as one dict"""

    async def call(**args):
        form_data = dict()
        form_data.update(quart.request.args.to_dict())
        xform = await quart.request.form
        # Pre-parse check for form data size
        if quart.request.content_type and any(
            x in quart.request.content_type
            for x in (
                "multipart/form-data",
                "application/x-www-form-urlencoded",
                "application/x-url-encoded",
            )
        ):
            if quart.request.content_length > config.server.max_form_size:
                await consume_body()
                return quart.Response(
                    status=413,
                    response=f"Request content length ({quart.request.content_length} bytes) is larger than what is permitted for form data ({config.server.max_form_size} bytes)!",
                )
        if xform:
            form_data.update(xform.to_dict())
        if quart.request.is_json:
            xjson = await quart.request.json
            form_data.update(xjson)
        try:
            resp = await func(form_data, **args)
            assert resp, "No response was provided by the underlying endpoint!"
        except Exception:  # Catch and spit out errors
            exc_type, exc_value, exc_traceback = sys.exc_info()
            err = "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            headers = {
                "Server": "ASF Selfserve Platform",
                "Content-Type": "text/plain",
            }
            # By default, we print the traceback to the user, for easy debugging.
            if config.server.error_reporting == "json":
                error_text = "API error occurred: \n" + err
                return quart.Response(headers=headers, status=500, response=error_text)
            # If client traceback is disabled, we print it to stderr instead, but leave an
            # error ID for the client to report back to the admin. Every line of the traceback
            # will have this error ID at the beginning of the line, for easy grepping.
            else:
                # We only need a short ID here, let's pick 18 chars.
                eid = str(uuid.uuid4())[:18]
                sys.stderr.write("API Endpoint %s got into trouble (%s): \n" % (quart.request.path, eid))
                for line in err.split("\n"):
                    sys.stderr.write("%s: %s\n" % (eid, line))
                return quart.Response(
                    headers=headers,
                    status=500,
                    response="API error occurred. The application journal will have information. Error ID: %s" % eid,
                )
        # If an error is thrown before the request body has been consumed, eat it quietly.
        if not quart.request.body._complete.is_set():
            await consume_body()

        return resp

    # Quart will, if no rule name is specified, default to calling the rule "call" here,
    # which leads to carps about duplicate rule definitions. So, given the fact that call()
    # is dynamically made from within this function, we simply adjust its internal name to
    # refer to the calling module and function, thus providing Quart with a much better
    # name for the rule, which will also aid in debugging.
    call.__name__ = func.__module__ + "." + func.__name__
    return call


def auth_failed():
    """Returns the appropriate authorization failure response, depending on auth mechanism supplied."""
    if "x-artifacts-webui" not in quart.request.headers:  # Not done via Web UI, standard 401 response
        headers = {"WWW-Authenticate": 'Basic realm="selfserve.apache.org"'}
        return quart.Response(status=401, headers=headers, response="Please authenticate yourself first!\n")
    else:  # Web UI response, do not send Realm header (we do not want a pop-up in our browser!)
        return quart.Response(status=401, response="Please authenticate yourself first!\n")


class FilenameConverter(werkzeug.routing.BaseConverter):
    """Simple converter that splits a filename into a basename and an extension"""

    regex = r"^[^/.]*(\.[A-Za-z0-9]+)?$"
    part_isolating = False

    def to_python(self, filename):
        extension = ""
        # If foo.bar, split into base and ext. Otherwise, keep filename as full string (even for .htaccess etc)
        if "." in filename[1:]:
            filename, extension = filename.split(".", maxsplit=1)
        return filename, extension
