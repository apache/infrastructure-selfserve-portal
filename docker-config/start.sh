#!/usr/bin/env bash

# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# script to start the selfserve app and related services

# create the key and cert needed for the mail server
(
    cd docker-config
    if [ ! -r cert.pem -o ! -r key.pem ] # could also check for a very old file?
    then
        openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'
    fi
)

# Start MySQL
pgrep mysqld || mysqld &

# Start Postgres
pgrep postgres || {
    sudo -u postgres PGDATA=$PGDATA /usr/lib/postgresql/16/bin/postgres >>/tmp/postgres.log 2>&1 &
}

# dummy server to emulate webmod.a.o/lists
pgrep python3 || (
    cd docker-config/webmod
    python3 webmod_server.py >/tmp/webmod_server.log 2>&1 &
)

sleep 1 # for database startup

# Create override config for use by docker
test -r selfserve-portal.yaml || cp docker-config/config.yaml selfserve-portal.yaml

cd server
python3 -m hypercorn -b 0.0.0.0:8000 server:application
