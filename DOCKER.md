<!---
 Licensed to the Apache Software Foundation (ASF) under one or more
 contributor license agreements.  See the NOTICE file distributed with
 this work for additional information regarding copyright ownership.
 The ASF licenses this file to You under the Apache License, Version 2.0
 (the "License"); you may not use this file except in compliance with
 the License.  You may obtain a copy of the License at

      http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
-->

# Docker instructions

This implementation is a work in progress; it is not yet a complete framework for local testing.

------

The following instructions assume a shell terminal at the top level of the source tree.
(i.e. where Dockerfile and compose.yaml are located)

At least two terminals are needed; one for the selfserve app, and another to capture emails.
An additional terminal may be used to connect to the running container.

# Build the image

    ```$ docker compose build```

# Start the container

    ```$ docker compose up```

# Configuration

The app uses `docker-config/config.yaml` directly, so changes to it take effect on the next start.

To customise the configuration locally, copy it to `selfserve-portal.yaml` at the top of the
source tree (this file is ignored by git) and edit the copy; it is then used instead.
If `docker-config/config.yaml` changes later, the start script prints a warning so you can
bring your copy up to date (or delete it to go back to the default).

# Logging in

The docker configuration turns on `debug_mode`, which replaces ASF OAuth with a development login.
Open http://localhost:8000/ and go to any page that needs a login; you are sent to a form where you
choose who to be: a user ID, the (P)PMCs they are on, and whether they are root, a Foundation member
or a chair. The password is `debug_password` from the configuration (`selfserve-dev` in
`docker-config/config.yaml`); the app also prints it at startup.

To switch identity, log out via http://localhost:8000/api/auth?logout=/ and log in again.
Sessions do not survive a restart of the app.

The development login only answers requests addressed to localhost (or 127.0.0.1 / [::1]), and
does nothing unless `debug_mode` is true. Never enable `debug_mode` in production.

Note: the docker LDAP stub knows made-up projects only (`aall`, `aamm`, ... `kkvv`); enter
those as (P)PMCs to try project-specific features.

# Start the mail server in the container

The container must be running.

    ```$ docker compose exec selfserve docker-config/smtpd.sh```

# Start a shell in the container

The container must be running.

    ```$ docker compose exec selfserve /bin/bash```

# Stop the container

    ```$ docker compose stop```

# Start the container without starting the self-serve app

For development testing, it may be useful to be able to restart the app
without restarting the container.

    ```$ docker compose run --rm -p8000:8000 --entrypoint /bin/bash selfserve```

The app can then be started as follows:

    ```$ docker-config/start.sh```

Press ^C to stop the app (this will take a few seconds).

The app can be restarted as above.

Note: if testing involves sending emails, also start the mail server as shown above
(in a separate terminal)
