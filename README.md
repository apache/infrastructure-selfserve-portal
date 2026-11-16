# ASF infrastructure self-serve portal platform

[![Lint](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/lint.yml/badge.svg?branch=main)](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/lint.yml?query=branch%3Amain)
[![Type check](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/typecheck.yml/badge.svg?branch=main)](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/typecheck.yml?query=branch%3Amain)

This repository houses the code for the ASF self-serve portal.
It is constructed as a [PipService](https://cwiki.apache.org/confluence/display/INFRA/Pipservices)
and houses the static site elements, documentation, and scripts required to perform self-serve
actions.

The layout is:

- `htdocs/`: The static site files
- `documentation/`: The documentation for the self-serve processes
- `server/`: The backend server (quart?) for the self-serve actions

