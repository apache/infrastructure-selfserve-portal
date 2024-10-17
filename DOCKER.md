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

The following instructions assume a shell terminal at the top level of the source tree.
(i.e. where Dockerfile and compose.yaml are located)

At least two terminals are needed; one for the selfserve app, and another to capture emails.
An additional terminal may be used to connect to the running container.

# Build the image

    ```$ docker compose build```

# Start the container

    ```$ docker compose up```

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
