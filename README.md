# ASF infrastructure self-serve portal platform

[![Lint](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/lint.yml/badge.svg?branch=main)](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/lint.yml?query=branch%3Amain)
[![Type check](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/typecheck.yml/badge.svg?branch=main)](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/typecheck.yml?query=branch%3Amain)
[![Test](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/apache/infrastructure-selfserve-portal/actions/workflows/test.yml?query=branch%3Amain)

This repository houses the code for the ASF self-serve portal.
It is constructed as a [PipService](https://cwiki.apache.org/confluence/display/INFRA/Pipservices)
and houses the static site elements, documentation, and scripts required to perform self-serve
actions.

The layout is:

- `htdocs/`: The static site files
- `documentation/`: The documentation for the self-serve processes
- `server/`: The backend server (quart?) for the self-serve actions

## Development

Dependencies are managed with [uv](https://docs.astral.sh/uv/): `pyproject.toml` declares them and
`uv.lock` pins them.

    uv sync                                    # create .venv with app + dev tools
    uv run pylint --recursive y server
    uv run mypy --ignore-missing-imports server
    uv run pytest                              # unit + integration
    uv run pytest --cov                        # with the coverage gate CI enforces

`requirements.txt` is generated from `uv.lock` for the production PipService deployment.
After changing dependencies (`uv add ...`), regenerate it (CI's *Requirements sync* workflow checks this):

    uv export --no-dev --no-hashes --no-emit-project --frozen -q -o requirements.txt

For a full local environment (databases, mail capture) see [DOCKER.md](DOCKER.md).

