# Mailing List Creation

## Summary
This feature allows projects or Foundation officers to create mailing lists under the
apache.org namespace.

## Canonical URL
https://selfserve.apache.org/mail.html

## Services managed by this feature
- Mailing list service (mailgw)
- Mailing list archives, https://lists.apache.org/

## Intended audience
This feature is intended for top-level projects and podlings, and Foundation officers.

## Access level(s) required
Access to this feature is as follows:
- PMC chairs: May request new mailing lists for the subdomain that corresponds to the project they are the chair of (for instance, the chair of the httpd project may create lists for `httpd.apache.org`)
- Foundation members: May request new mailing lists for the entire `*.apache.org` namespace

Creation of mailing lists is delayed by 24 hours by design, to allow for human audit of the request, if needed.
This process may be expedited by Infrastructure if deemed necessary.

## Notification scheme
When a new mailing list is requested, a receipt of the request is sent to the requestor and to the Infrastructure private list.
Once the list has been created (after the delay mentioned earlier), a notification will be sent to both
[notifications@infra.apache.org](https://lists.apache.org/list.html?notifications@infra.apache.org) and,
if the mailing list belongs to a project, the private list of said project.
