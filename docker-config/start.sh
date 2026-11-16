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
# (match on the script name: other python3 processes, e.g. the mail server, may already be running)
pgrep -f '^python3 webmod_server.py' >/dev/null || (
    cd docker-config/webmod
    python3 webmod_server.py >/tmp/webmod_server.log 2>&1 &
)

sleep 1 # for database startup

# Configuration: use docker-config/config.yaml as-is, so changes to it always take effect.
# To customise it, copy it to selfserve-portal.yaml (gitignored) and edit the copy; it is then used instead.
if [ -n "$SELFSERVE_CONFIG" ]
then
    echo "Using configuration from SELFSERVE_CONFIG=$SELFSERVE_CONFIG"
elif [ -r selfserve-portal.yaml ]
then
    echo "Using local configuration override selfserve-portal.yaml"
    if [ docker-config/config.yaml -nt selfserve-portal.yaml ]
    then
        echo "WARNING: docker-config/config.yaml has changed since selfserve-portal.yaml was last edited."
        echo "WARNING: Compare the two, or delete selfserve-portal.yaml to use docker-config/config.yaml directly."
    fi
else
    export SELFSERVE_CONFIG="$PWD/docker-config/config.yaml"
    echo "Using configuration from docker-config/config.yaml"
fi

cd server
python3 -m hypercorn -b 0.0.0.0:8000 server:application
