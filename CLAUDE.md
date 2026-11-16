# CLAUDE.md

ASF self-serve portal (selfserve.apache.org): lets committers/PMCs request Jira & Confluence accounts,
create Jira projects / Confluence spaces, and queue mailing-list creation. Python [asfquart](https://github.com/apache/infrastructure-asfquart)
(Quart) backend in `server/`, static Bootstrap + vanilla-JS frontend in `htdocs/`. Deployed as a PipService.

This file is shared by the team. When Claude gets something wrong here, add a line so it doesn't happen again.

## Commands

```bash
docker compose build                                   # image with MySQL, Postgres, fake webmod, smtpd
docker compose up                                      # app on http://localhost:8000
docker compose exec selfserve docker-config/smtpd.sh   # capture outgoing email (separate terminal)
docker compose run --rm -p8000:8000 --entrypoint /bin/bash selfserve   # then docker-config/start.sh to restart app only
uv sync                                                # .venv with app + dev deps (pinned pylint/mypy, same as CI)
uv run pylint --recursive y server                     # lint (config: pylintrc)
uv run mypy --ignore-missing-imports server            # types
uv run pytest tests                                    # run from repo root
```

Inside the docker container the same tools are installed into the system Python, so drop the `uv run`.
`bonsai` needs libsasl2/libldap headers to build on the host; if `uv sync` fails there, use the container.
CI runs on every push against Python 3.10, 3.12 and 3.14: `.github/workflows/lint.yml` (pylint) and
`typecheck.yml` (mypy), kept separate so each has its own README badge. Both get their environment from
the composite action `.github/actions/setup-python-uv` (Python, uv, apt libs, `uv sync`, shared uv cache);
new CI workflows should use it too, and Python versions are listed in each workflow's matrix.
Code must stay 3.10-compatible (`requires-python`, pylint `py-version`). `pylintrc` has `fail-under=10.0`, so **any** pylint
message fails the build. Run both before pushing.

## Dependencies (uv)

- `pyproject.toml` + `uv.lock` are the source of truth. Add/remove with `uv add <pkg>` / `uv add --dev <pkg>`; never hand-edit `uv.lock`.
- `requirements.txt` is **generated** for production (the PipService host still installs it with pipenv). After any dependency change, regenerate it — CI fails if it drifts:
  `uv export --no-dev --no-hashes --no-emit-project --frozen -q -o requirements.txt`
- Dev tools (pylint, mypy, pytest) live in the `dev` group and are pinned; bump them deliberately.
- Don't change `pipservice-selfserve-portal.service` or remove `requirements.txt` without coordinating with the production deployment.

## Layout

- `server/server.py` → `app.main()`; the app **must run with cwd `server/`** (paths like `../htdocs`, `../roleaccounts.txt`, `../selfserve-portal.yaml` are relative to it).
- `server/app/endpoints/*.py` — one module per feature, registered by import in `endpoints/__init__.py`.
- `server/app/lib/` — `config` (YAML → module globals + LDAP/webmod/whimsy refresh loops), `middleware`, `email`, `log` (incl. Slack), `utils` (validators), `tokens` (role-account bearer tokens).
- `server/email_templates/*.txt` — `subject\n--\nbody`, rendered with `str.format(**variables)`.
- `htdocs/*.html` — page *fragments*; `htdocs/js/selfserve.js` — all frontend logic.
- `documentation/*.md` — policy docs. Not rendered by the app; user-facing text lives in `htdocs/`.
- `docker-config/` — local-dev only (fake services, DB setup, `config.yaml` copied to `selfserve-portal.yaml`).

## How things work (gotchas)

- **HTML is compiled at startup**: each `htdocs/*.html` is wrapped in `htdocs/templates/master.html` and written to `htdocs/compiled/` (gitignored). Edits to HTML or `selfserve.js` need an app restart (SRI hashes for scripts are computed then too). Never edit `compiled/`.
- **Config loads at import time** (`lib/config.py`). Prod uses `/opt/selfserve-portal/selfserve-portal.yaml` if present, else `server/config.yaml`. Endpoint modules create SQLite tables in `storage.db_dir` on import.
- **Asserts are load-bearing**: modules raise if `__debug__` is false. Never run with `python -O`. Keep the `if not __debug__: raise` guard in new modules.
- **Validation idiom**: `assert cond, "user-facing message"` inside `try/except AssertionError as e: return {"success": False, "message": str(e)}`. Responses are JSON `{"success": bool, "message": str}`.
- **Auth**: `@asfquart.auth.require(any_of={R.pmc_member, R.root, ...})` with `from asfquart.auth import Requirements as R`; session via `await asfquart.session.read()`; form/JSON via `await asfquart.utils.formdata()`. Root (`session.isRoot`) generally bypasses project checks — preserve that.
- **Mailing lists are queued, not created**: requests are JSON files in `storage.queue_dir`; external tooling pulls them via `GET /api/queue` (role account) and removes with `?rm=<file>`.
- **Jira/Confluence actions shell out to ACLI** (`/opt/jira-cli/acli.sh`, `/opt/confluence-cli/acli.sh`) — only present in prod. Use `asyncio.create_subprocess_exec` with an argument list, never a shell string.
- Email templates use `str.format`: literal `{`/`}` must be doubled. Missing variables raise at send time.
- Anything touching email, Slack, LDAP, Jira, or Confluence hits **real ASF services** unless you're in the docker setup. Don't point a dev instance at prod config.

## Adding a feature

1. Endpoint module in `server/app/endpoints/`, add it to `endpoints/__init__.py`.
2. Page fragment `htdocs/<feature>.html` + functions in `selfserve.js` named `<feature>_<verb>` using the `GET`/`POST` helpers and `toast()`.
3. Link it from `htdocs/index.html` and the nav in `htdocs/templates/master.html`.
4. Email templates in `server/email_templates/`; policy doc in `documentation/`.

## Style

- Target Python 3.10 (pylint `py-version`); async everywhere in request paths.
- New source files get the ASF license header (copy from an existing file).
- Frontend: no build step, no npm, no frameworks. Bootstrap 5 + Font Awesome are vendored in `htdocs/`.
- Small PRs against `main`; reference the INFRA Jira ticket (`INFRA-12345: ...`) in commits when there is one.
