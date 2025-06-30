#!/usr/bin/env python3

import requests
import asyncio
import argparse
import sys
import json

# authenticate via user/pass to obtain token
authurl = "https://hub.docker.com/v2/users/login"
baseurl = "https://hub.docker.com/"

data = {
  "username": "user",
  "password": "pass"
}

response = requests.post(authurl, json=data)
bearer_token = response.json().get("token")

headers = {"Authorization": f"Bearer {bearer_token}",'Content-type': 'application/json'}

# The API endpoints
org_name = 'apache'
getusers = 'https://hub.docker.com/v2/orgs/apache/scim/2.0/Users'
getgroups = 'https://hub.docker.com/v2/orgs/apache/groups'

async def main():

  user = args.user
  group = args.group

  invitedata = {
    "org": org_name,
    "team": group,
    "role": "member",
    "invitees": [
      user
    ],
  # "dry_run": True
}

  addusertoorg = requests.post("https://hub.docker.com/v2/invites/bulk",headers=headers, json=invitedata)
  print(addusertoorg)

if __name__ == "__main__":
    # check for any input args
    parser = argparse.ArgumentParser(description = "Add Dockerhub User and add to a Group")
    parser.add_argument("-u", "--user", help = "Dockerhub Username or email address of person being invited.", type = str, required = True)
    parser.add_argument("-g", "--group", help = "Name of an existing group to add the user to", type = str, required = True) 

    args = parser.parse_args()

# Default modern behavior (Python>=3.7)
    if sys.version_info.minor >= 7:
        asyncio.run(main())
    # Python<=3.6 fallback
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
