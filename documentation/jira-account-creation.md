# Jira Account Creation

## Summary
This feature helps projects create Jira accounts for users wishing to interact with projects using the 
Jira issue tracker for development purposes. As public signup for Jira accounts has been disabled 
(as per [this thread](https://lists.apache.org/thread/jx9d7sp690ro660pjpttwtg209w3m39w)), projects 
and new contributors will now need to use this tool to set up accounts for new users.

## Canonical URL
https://selfserve.apache.org/jira-acct.html

## Service managed by this feature
- Jira issue tracking platform, https://issues.apache.org/jira/

## Intended audience
This feature is intended for contributors of both top-level projects and podlings.

## Access level(s) required
Contributors can request an account anonymously.

Full access to accepting/denying account requests is granted to anyone on a PMC or PPMC.

## Data gathered
- Public name
- Email address
- The project that the account request relates to
- A short description of the intended use of the account

Only the description and the contributor's username will be relayed to projects for assessment.
The email address and public name will not be passed on.

## Notification scheme
Account creations will notify [private@$project.apache.org] for provenance and audit reasons.
The original account requestor will also be notified via email with a detailed description of how to proceed with the new account.

If the request is not approved, notification goes to the project PMC involved and to the requestor.
