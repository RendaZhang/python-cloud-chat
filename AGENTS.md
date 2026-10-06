# AGENTS.md

Last updated: 2026-10-06

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

## Git Workflow And Slice Cleanup

- Use one development trunk: `master`. Small documentation/copy changes and narrow
  fixes may use clean, synchronized master directly. Dependency upgrades,
  architecture changes and larger behavior changes use a short-lived
  `codex/<description>` branch. PRs are optional for owner-operated slices;
  there is no permanent develop branch or mandatory multi-stage Git Flow.
- At slice start, check status, refresh remote refs, read the current docs and
  confirm task ownership and `git worktree list`. One writer per checkout;
  switching branches does not isolate concurrent tasks. Preserve others' changes.
- Validate the scoped change with the pinned runtime and normal hooks. Integrate
  a completed branch into clean master with `git merge --ff-only`; if master
  moved, reconcile and revalidate rather than force-pushing. Push master only
  when deployment is authorized; it triggers production delivery.
- At slice finish, verify the exact source SHA's workflow and production checks,
  then remove the owned branch only after checking merged ancestry, worktree
  usage and open PR dependencies. Delete the remote branch if one was published.
  GitHub auto-deletes merged PR heads, not local or manually integrated branches.
- Stop owned temporary processes and report clean status or explain leftovers.
  Never discard failed/in-progress work just to clean up. Unmerged branches or
  stashes may be deleted only after explicit owner abandonment; no archive is
  required for an explicitly cancelled experiment.
- Preserve master, release branches/tags and other tasks' worktrees/stashes.
  Close superseded Dependabot PRs with the current fix/version evidence before
  deleting their branches; keep unresolved alerts and future updates enabled.

## Runtime Context

- Language/runtime: Python 3.13.
- Framework: Flask.
- Production server: Gunicorn with gevent workers.
- Session/cache/rate-limit dependency: Redis.
- Persistent auth data: PostgreSQL through PgBouncer.
- Public API prefix: `/cloudchat`.
- Internal Flask routes are documented in `docs/API.md`; external callers use
  the Nginx prefix.

## Local Development

- Use Python 3.13 for parity with production.
- Runtime version files are committed for local tooling:
  - `.python-version` for pyenv-compatible Python selection.
  - `.mise.toml` for mise-based Python selection.
- `mise` is not macOS-only. For Windows agents, prefer WSL2 + Ubuntu + mise as
  the supported local-development baseline. Native Windows PowerShell + mise may
  work, but Python native dependencies and path behavior must be revalidated
  before treating it as equivalent.
- This repository's `.mise.toml` and `.python-version` are authoritative for the
  backend Python runtime. A developer machine may also keep a non-committed
  parent workspace `.mise.toml` to provide shared defaults for sibling
  repositories, but agents must not rely on that file being present after
  cloning only this repository.
- If a non-interactive shell resolves Homebrew/system Python instead of mise,
  check that `~/.local/share/mise/shims` is on `PATH` and run `mise doctor`.
  Do not fix backend scripts by hard-coding local Python installation paths.

```bash
mise install
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Use placeholder values for local environment variables. Never commit `.env`,
real API keys, database URLs with passwords, SMTP credentials, or copied
production environment files.

## Validation

GitHub Actions runs the repository's backend quality gates on pull requests,
pushes to `master`, and manual dispatches. Reproduce the same gates locally with
the committed Python runtime before pushing:

```bash
python -m pip check
python -m compileall app.py app_auth.py chat_guide_prompt.py db.py mailer.py models.py security_policy.py
ruff check .
black --check .
bash -n scripts/deploy_production.sh
python -m unittest discover -s tests
pre-commit run --all-files
```

For dependency changes, also run a current `pip-audit` against the committed
requirements from an isolated temporary environment. Do not add audit tooling
to the production virtualenv solely to run this check. Record any remaining
advisory by package, version, affected path, mitigation, and fixed-version
availability instead of treating a raw finding count as exploitability proof.

The standard-library tests under `tests/` are focused on the Chat Guide prompt
boundary and related route-source contracts. They are not broad API,
authentication, database, Redis, streaming, or production integration coverage.

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
- Public JSON inputs, Host trust, Chat message/history/rate budgets, required
  startup configuration, Redis/model timeouts, and reset-link construction are
  centralized in `security_policy.py`. Keep route-specific business behavior in
  `app.py` and `app_auth.py`; do not bypass the shared boundary with raw
  `request.json` access.
- New password-reset emails use `/reset_password#token=...`. The frontend accepts
  that fragment plus legacy query links and immediately clears either form from
  the address bar. Never log or persist a raw reset link or token outside the
  existing short-lived Redis record and outbound email.
- The health endpoint should remain safe for read-only uptime checks.

## Deployment

- `.github/workflows/backend-ci.yml` owns the normal backend release flow.
  Pull Requests run quality gates only. A push to `master`, or a manual dispatch
  targeting `master`, deploys only after the same quality job succeeds.
- `scripts/deploy_production.sh` owns the existing production-side sync, dependency,
  unit, restart and health logic. The workflow checks out its exact source commit,
  prepares SSH, and streams this script to the server with `bash -s --` and the
  deployment path, target SHA and force-restart flag. Do not execute the production
  script on a developer machine or call an older server-side copy before syncing.
  Keep deployment behavior changes in this script rather than embedding them in YAML.
- The deploy job serializes production updates, refuses tracked production
  changes or non-fast-forward targets, and verifies that the production
  checkout ends at the exact GitHub Actions commit.
- `deploy/cloudchat.service` is the canonical production unit. The deploy job
  keeps the checkout, venv, environment file, and service management root-owned,
  while the Gunicorn/Flask process runs as the locked `cloudchat` system user and
  binds only `127.0.0.1:5000`.
- Unit installation must remain fail-safe: validate the dedicated account and
  unit, prove an isolated `127.0.0.1:5001` candidate, back up the prior unit,
  install atomically, and restore the prior unit if identity, listener, service,
  or health checks fail. Never print or loosen the root-only EnvironmentFile.
- `requirements.txt` changes update the existing Python 3.13.14 virtual
  environment. Runtime Python or dependency changes restart only
  `cloudchat.service`; canonical-unit changes or drift also require a restart,
  while docs/workflow-only changes synchronize without one. The manual
  `force_restart` input exercises the same controlled one-service restart path.
- Every deployment verifies canonical-unit equality, non-root identity, empty
  capabilities, the sole loopback listener, service state, and internal/public
  health.
  Do not manually pull or restart production to hide a failed workflow; repair
  the workflow with a normal follow-up commit or report an explicitly approved
  recovery action.
- Routine delivery ends with the exact pushed commit's successful workflow and
  health checks, not a separate manual SSH/pull/restart step. Docs-only pushes
  use this same automatic synchronization path. Inspect the matching run with:

  ```bash
  gh run list --workflow backend-ci.yml --branch master --event push --commit "$(git rev-parse HEAD)" --limit 1
  gh run view <matching-run-id> --log
  ```

- When delivering changes across the three repositories, finish one repository's
  deployment and health verification before pushing the next. A successful run
  for an older commit is not evidence for the current change.

- Do not restart Nginx, Redis, PostgreSQL, or unrelated services for backend-only
  changes unless the task explicitly requires it.
- Do not hand-edit `/etc/systemd/system/cloudchat.service` as a lasting fix.
  Change and test the tracked canonical unit, then use the exact-SHA workflow.

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
