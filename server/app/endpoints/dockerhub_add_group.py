#!/usr/bin/env python3

import requests
import asyncio
import argparse
import sys
import json

"""
This script create a Dockerhub Group (team) in the 'apache' org
in Dockerhub.
"""

# TODO: A group is no use without members, add one at the same time?

# authenticate via user/pass to obtain token
authurl = "https://hub.docker.com/v2/users/login"
baseurl = "https://hub.docker.com/"

data = {
  "username": "user",
  "password": "pass"
}

response = requests.post(authurl, json=data)
bearer_token = response.json().get("token")
# print(bearer_token)
headers = {"Authorization": f"Bearer {bearer_token}",'Content-type': 'application/json'}
headers_nojson = {"Authorization": f"Bearer {bearer_token}"}

# The API endpoints
org_name = 'apache'
getusers = 'https://hub.docker.com/v2/orgs/apache/scim/2.0/Users'
getgroups = 'https://hub.docker.com/v2/orgs/apache/groups'

async def main():

  group = args.group
  description = args.description

  groupdata = {
    "name": group,
    "description": description
  }

  creategroup = requests.post(f"https://hub.docker.com/v2/orgs/{org_name}/groups", headers=headers, json=groupdata)
  print(creategroup.json())
  # print(headers)


  # Fetch the group id, so it can be used 
  # fetch_group_id = requests.get(f"https://hub.docker.com/v2/orgs/{org_name}/groups/{group}",
  #   headers=headers)

  # print(fetch_group_id.json())
  # groupid = fetch_group_id.json()['id']


if __name__ == "__main__":
    # check for any input args
    parser = argparse.ArgumentParser(description = "Add Dockerhub Group")
    parser.add_argument("-g", "--group", help = "Name of group to create", type = str, required = True)
    parser.add_argument("-d", "--description", help = "Description of group [optional]", type = str, required = False, default ='') 

    args = parser.parse_args()

# Default modern behavior (Python>=3.7)
    if sys.version_info.minor >= 7:
        asyncio.run(main())
    # Python<=3.6 fallback
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())

