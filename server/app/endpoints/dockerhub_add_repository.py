#!/usr/bin/env python3

import requests
import asyncio
import argparse
import sys
import json

"""
This script create a Dockerhub repository in the 'apache' org 
in Dockerhub and then adds an already existing auth group/team 
to the repository with write/admin access.
"""

# TODO: Would be ideal if a group was needed to be created at the same
#       time as a new repo creation.

# TODO: Check if repository being requested already exists.

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
headers_nojson = {"Authorization": f"Bearer {bearer_token}"}


# The API endpoints
org_name = 'apache'
getusers = 'https://hub.docker.com/v2/orgs/apache/scim/2.0/Users'
getgroups = 'https://hub.docker.com/v2/orgs/apache/groups'

# add a repository to the 'apache' org in Dockerhub

async def main():
  new_repo = args.repository
  summary = args.summary
  description = args.description
  categories = "apache"
  categories_array = json.dumps(categories)
  group = args.group

  print(categories_array)

###
  payload = {
      'description': summary,
      'full_description': description,
      'categories': [categories], #TODO: this doesnt work
      'is_private': False,
      'name': new_repo,
      'namespace': org_name
  }
  resp = requests.post(
      'https://hub.docker.com/v2/repositories/',
      json=payload,
      headers=headers,
  )
  print(resp.json())

  add_group_to_repository(group,new_repo)
###

def add_group_to_repository(group,repo):

  group_name = group
  new_repo = repo

  # Fetch the group id, so it can be used
  fetch_group_id = requests.get(f"https://hub.docker.com/v2/orgs/{org_name}/groups/{group_name}",
    headers=headers)

  print(fetch_group_id.json())

  groupid = fetch_group_id.json()['id']

  addgrouptorepository = requests.post(f"https://hub.docker.com/v2/repositories/{org_name}/{new_repo}/groups",
    json={'group_id': groupid, 'permission':'write'},
    headers=headers  # with json
  )

# end def
 
if __name__ == "__main__":
    # check for any input args
    parser = argparse.ArgumentParser(description = "Add Dockerhub repository")
    parser.add_argument("-r", "--repository", help = "Name of repository to create", type = str, required = True)
    parser.add_argument("-s", "--summary", help = "Short description of repository [optional]", type = str, required = False, default ='')
    parser.add_argument("-d", "--description", help = "Long description of repository [optional]", type = str, required = False, default ='') 
    parser.add_argument("-g", "--group", help = "Name of existing auth group to associate with the repository", type = str, required = True)

    args = parser.parse_args()

# Default modern behavior (Python>=3.7)
    if sys.version_info.minor >= 7:
        asyncio.run(main())
    # Python<=3.6 fallback
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
