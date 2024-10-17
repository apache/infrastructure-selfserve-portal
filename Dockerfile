#
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
#

FROM ubuntu:24.04

ENV \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && \
    DEBIAN_FRONTEND='noninteractive' apt-get install -y \
    curl git vim python3-pip

# for bonsai
RUN  DEBIAN_FRONTEND='noninteractive' apt-get install -y \
    libsasl2-dev libldap-dev

# for local database
RUN  DEBIAN_FRONTEND='noninteractive' apt-get install -y \
    sqlite3

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt  --break-system-packages

# database
RUN  DEBIAN_FRONTEND='noninteractive' apt-get install -y \
    mysql-server

# local email server to capture emails
RUN  DEBIAN_FRONTEND='noninteractive' apt-get install -y \
    python3-aiosmtpd

# PSQL for Jira
RUN  DEBIAN_FRONTEND='noninteractive' apt-get install -y \
    sudo postgresql postgresql-contrib

# Needed for aiomysql? (MOVE EARLIER?)
RUN  DEBIAN_FRONTEND='noninteractive' apt-get install -y \
    python3-cryptography

ENV PGDATA /etc/postgresql/16/main/

COPY docker-config/pgsetup.sh /tmp/
RUN bash /tmp/pgsetup.sh

COPY docker-config/mysetup.sh /tmp/
RUN bash /tmp/mysetup.sh

RUN ln -s /opt/selfserve-portal/docker-config/asfldapsearch.sh /usr/bin/asfldapsearch

WORKDIR /opt/selfserve-portal


ENTRYPOINT ["bash", "docker-config/start.sh"]
# https://www.digitalocean.com/community/tutorials/how-to-install-postgresql-on-ubuntu-20-04-quickstart
