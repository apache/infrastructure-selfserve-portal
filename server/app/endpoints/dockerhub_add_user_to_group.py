#!/usr/bin/env python3

import requests
import asyncio
import argparse
import sys
import json

"""
This script adds a user to a group (team) in the 'apache' org
in Dockerhub.
"""

# TODO: If the user is not part of the 'apache' org, then invite them.

# authenticate via user/pass to obtain token
authurl = "https://hub.docker.com/v2/users/login"
baseurl = "https://hub.docker.com/"

data = {
  "username": "user",
  "password": "pass"
}

response = requests.post(authurl, json=data)
print(f'Total users: {response.json().get("total")}')
bearer_token = response.json().get("token")

headers = {"Authorization": f"Bearer {bearer_token}",'Content-type': 'application/json'}
headers_nojson = {"Authorization": f"Bearer {bearer_token}"}

# The API endpoints
org_name = 'apache'
getusers = 'https://hub.docker.com/v2/orgs/apache/scim/2.0/Users'
getgroups = 'https://hub.docker.com/v2/orgs/apache/groups'

async def main():

  user = args.user
  group = args.group

  userdata = { "member": user }

  addusertogroup = requests.post(f"https://hub.docker.com/v2/orgs/{org_name}/groups/{group}/members", headers=headers, json=userdata)
  print(addusertogroup)

###

if __name__ == "__main__":
    # check for any input args
    parser = argparse.ArgumentParser(description = "Add User to aDockerhub Group")
    parser.add_argument("-u", "--user", help = "Name of user to add to the group", type = str, required = True)
    parser.add_argument("-g", "--group", help = "Name of (currently existing) group", type = str, required = True)

    args = parser.parse_args()

# Default modern behavior (Python>=3.7)
    if sys.version_info.minor >= 7:
        asyncio.run(main())
    # Python<=3.6 fallback
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

