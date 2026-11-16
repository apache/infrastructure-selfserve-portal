# Matomo Property Creation

## Summary
This feature lets projects set up a new property (site) in the ASF's Matomo web analytics instance.
The requester gets the new site ID and the JavaScript tracking code to add to their pages.

## Canonical URL
https://selfserve.apache.org/matomo.html

## Service managed by this feature
- Matomo web analytics, https://analytics.apache.org/

## Intended audience
This feature is intended for top-level projects and podlings.

## Access level(s) required
Any member of a project's PMC (or PPMC) can request properties for that project.
Infrastructure (root) can request properties for any project.

## How it works
- The site URL must use https and be on the project's own domain (for instance `https://zeppelin.apache.org`)
  or one of its subdomains, optionally under a path (for instance `https://zeppelin.apache.org/docs`).
- The project's main website is named after the project, e.g. `Apache Zeppelin`.
  Any other site needs a short label, which is added to the name, e.g. `Apache Zeppelin - Documentation`.
- A project can have several properties, but only one per site URL. Requests for a URL that Matomo
  already tracks are refused (`http`/`https` and `www.` variants count as the same URL).
- New properties get public (anonymous) view access, like all existing ASF properties.

## Notification scheme
Once the property is created, the site ID, a link to its reports and the tracking code are shown to the requester
and emailed to the project's private list, the requester, and the Infrastructure team.
The Infrastructure team is also notified via Slack for provenance and audit reasons.

## Configuration
The portal reads the Matomo instance URL and API token from a separate YAML file,
whose path is set as `matomo.credentials` in the portal configuration (default `/opt/selfserve-portal/matomo.yaml`).
This file is deployed by puppet, so that each node can point at the right instance (dev or prod).
See `matomo.example.yaml` for its format. The token must belong to a Matomo superuser.
If the file is missing or incomplete, the feature tells requesters to contact the Infrastructure team.
