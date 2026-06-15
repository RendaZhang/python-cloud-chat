# AGENTS.md

Last updated: 2026-06-15

This file gives AI coding agents the project context needed to work safely in the
`python-cloud-chat` backend repository. The repository is public, so do not add
secrets, private host details, real environment values, SSH keys, cookies,
database credentials, API keys, SMTP passwords, or tokens to this file or to any
committed document.

## Project Role

- This repository contains the CloudChat Flask backend used by
  `www.rendazhang.com`.
- Production traffic is routed by Nginx under `/cloudchat/*`.
- The service provides authentication, password reset, health checks, and
  streaming chat APIs.
- Related repositories:
  - `rendazhang`: Astro + React frontend.
  - `nginx-conf`: production Nginx config, security headers, and server runbook.

## First Steps For Every Task

1. Run `git status --short --branch`.
2. Read the relevant docs before changing behavior:
   - `README.md`
   - `docs/API.md`
   - `docs/TESTING.md`
   - `docs/LIGHTWEIGHT_BACKEND_DEVELOPMENT.md`
   - `docs/TROUBLESHOOTING.md`
   - `docs/REQUIREMENTS.md`
3. Keep changes scoped to backend code and backend docs.
4. Do not change Nginx config from this repo.
5. Do not use `--no-verify` unless the reason is explicit and documented.
6. Do not force push.

## Runtime Context

- Language/runtime: Python 3.12.
- Framework: Flask.
- Production server: Gunicorn with gevent workers.
- Session/cache/rate-limit dependency: Redis.
- Persistent auth data: PostgreSQL through PgBouncer.
- Public API prefix: `/cloudchat`.
- Internal Flask routes are documented in `docs/API.md`; external callers use
  the Nginx prefix.

## Local Development

- Use Python 3.12 for parity with production.
- Runtime version files are committed for local tooling:
  - `.python-version` for pyenv-compatible Python selection.
  - `.mise.toml` for mise-based Python selection.

```bash
mise install
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Use placeholder values for local environment variables. Never commit `.env`,
real API keys, database URLs with passwords, SMTP credentials, or copied
production environment files.

## Validation

There is currently no broad pytest suite in this repository. Use the strongest
available checks for the change scope:

```bash
python -m compileall app.py app_auth.py db.py mailer.py models.py
ruff check .
black --check .
pre-commit run --all-files
```

For API behavior changes, also run targeted curl checks against an authorized
local or production-safe environment, following `docs/TESTING.md`. Do not run
destructive or account-spamming tests against production without explicit
approval.

## API And Frontend Contracts

- All browser requests that depend on cookies must use `credentials: 'include'`
  on the frontend.
- Streaming chat returns newline-delimited JSON chunks with a `text` field.
  Coordinate parser contract changes with the frontend repository.
- Authentication cookie behavior, password reset behavior, and rate limits are
  public API contracts. Update `docs/API.md` and `docs/TESTING.md` when these
  change.
- The health endpoint should remain safe for read-only uptime checks.

## Deployment

- Normal backend release flow:
  1. Commit and push this repository.
  2. On the authorized production server, update the backend Git worktree with:

     ```bash
     cd /opt/cloudchat
     git pull --ff-only origin master
     ```

  3. For code or dependency changes, update the virtual environment if needed
     and restart only `cloudchat.service`.
  4. For docs-only changes, no service restart is needed.

- Do not restart Nginx, Redis, PostgreSQL, or unrelated services for backend-only
  changes unless the task explicitly requires it.

## Security Rules

- Do not print or commit production environment files.
- Do not log secrets, password reset tokens, cookies, or authorization data.
- Keep examples masked with placeholders such as `***` or `<TOKEN>`.
- Any change to authentication, password reset, session storage, or rate limits
  should include an explicit security review note in the final report.

## Documentation Rules

- Public docs may mention repository names, public paths, public URLs, endpoint
  names, and placeholder environment variable names.
- Public docs must not include real secret values, private keys, cookies,
  session data, database passwords, or SMTP credentials.
- Update docs in the same commit as behavior changes.

## Final Report Checklist

When handing work back, include:

- What changed.
- What validation commands ran.
- Deployment/sync status.
- Whether `cloudchat.service` was restarted.
- Any remaining risk or follow-up slice.
