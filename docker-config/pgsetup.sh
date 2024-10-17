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


# Script to set up the PGSQL database.

# Must agree with ENV defintion
PGDATA=/etc/postgresql/16/main

sudo -u postgres PGDATA=$PGDATA /usr/lib/postgresql/16/bin/postgres &
sleep 1 # should be enough, but just in case:
until pg_isready -h localhost -p 5432
do
  echo "Waiting for PostgreSQL to start..."
  sleep 1
done
sudo -u postgres PGDATA=$PGDATA createuser -s root
sudo -u postgres PGDATA=$PGDATA createdb jira

cat <<EOD | psql -d jira
CREATE USER psql WITH PASSWORD 'psql'\g
create table cwd_user(lower_user_name varchar(255), email_address varchar(255), directory_id int)\g
GRANT SELECT, UPDATE, INSERT ON cwd_user TO psql\g
EOD

sudo -u postgres PGDATA=$PGDATA /usr/lib/postgresql/16/bin/pg_ctl stop -m smart
