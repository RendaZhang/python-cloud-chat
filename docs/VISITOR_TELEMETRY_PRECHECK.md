<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Visitor Telemetry Backend Precheck](#visitor-telemetry-backend-precheck)
  - [Decision](#decision)
  - [Evidence Reviewed](#evidence-reviewed)
  - [Option Evaluation](#option-evaluation)
  - [Future Aggregate-Only Design](#future-aggregate-only-design)
    - [Route Shape](#route-shape)
    - [Allowed Event Contract](#allowed-event-contract)
    - [Rejected Data](#rejected-data)
    - [Persistence Shape](#persistence-shape)
    - [Retention](#retention)
    - [Privacy Note](#privacy-note)
  - [Validation Plan For A Future Go Slice](#validation-plan-for-a-future-go-slice)
  - [Deployment Requirements For A Future Go Slice](#deployment-requirements-for-a-future-go-slice)
  - [Rollback Plan For A Future Go Slice](#rollback-plan-for-a-future-go-slice)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Visitor Telemetry Backend Precheck

- **Last Updated**: July 02, 2026, 18:00 (UTC+08:00)
- **Scope**: Phase 11 backend telemetry API precheck only.
- **Status**: No endpoint, schema, Redis key, retention job, dependency, runtime, Nginx, or service
  change is implemented by this document.

## Decision

The Slice 11.5 decision is **No-Go for backend visitor telemetry transport now**.

Keep the frontend visitor event boundary local/no-op until there is a concrete product question
that cannot be answered with manual QA, public feedback, or local development logging. The current
site has a strict privacy boundary, low operational tolerance for unnecessary server state, and no
evidence yet that persisted visitor telemetry would materially improve the visitor journey.

If the owner later reopens this decision, the smallest acceptable design is **aggregate-only
PostgreSQL counters**. Short-retention raw events are not justified for the current site.

## Evidence Reviewed

Current backend facts:

- The Flask app exposes chat, reset, cache test, auth, password reset, and health endpoints.
- Redis already supports Flask session storage, auth sessions, password reset tokens, and rate
  limiting.
- PostgreSQL is used for persistent auth data through SQLAlchemy.
- Nginx proxies `/cloudchat/*` to Flask and already forwards `X-Real-IP` and `X-Forwarded-For`.
- Chat messages are stored in the existing Flask session for the chat experience; visitor telemetry
  must not copy chat text, generated answers, or session contents.
- Existing auth models include user, credential, and session data. Visitor telemetry must not reuse
  auth/profile identifiers, email, phone, raw IP fields, or raw user-agent storage patterns.

Current frontend facts:

- `rendazhang/src/services/visitorEvents.ts` already normalizes controlled event names and payload
  keys.
- The default visitor event transport is a no-op.
- Chat preset telemetry currently carries only `chat_preset_question_clicked` with a controlled
  `presetId`.
- Preset answers are grounded from public context, but visitor input and generated answers are not
  telemetry data.

## Option Evaluation

| Option | Decision | Rationale |
| --- | --- | --- |
| No persistence | Recommended now | Lowest privacy and operations risk; preserves the current no-op frontend boundary; no API spam surface, schema migration, retention job, or production restart. |
| Redis aggregate counters | Not recommended for durable telemetry | Redis is already important for sessions and rate limits on a small server. Durable reporting would need extra key naming, rollup/export logic, and memory/eviction review. Redis remains acceptable only for future request rate limiting. |
| PostgreSQL aggregate counters | Acceptable only if reopened | PostgreSQL is the right durable store if the owner later needs first-party counts. Store daily aggregate rows only, never raw event rows. |
| Short-retention raw events | No-Go | Raw rows add retention, cleanup, review, abuse, and privacy risk without current evidence. They also increase the chance of accidentally storing visitor-entered text or private request metadata. |

## Future Aggregate-Only Design

This section is a design guardrail for a later explicit Go decision. It is not implemented now.

### Route Shape

External route:

```text
POST /cloudchat/telemetry/events
```

Internal Flask route after Nginx prefix stripping:

```text
POST /telemetry/events
```

Request body:

```json
{
  "schemaVersion": 1,
  "name": "chat_preset_question_clicked",
  "payload": {
    "presetId": "personalweb_proof"
  }
}
```

Response behavior:

- `204 No Content` for accepted aggregate increments.
- `400` for unknown event names, unknown keys, missing required keys, invalid values, sensitive
  keys, or sensitive values.
- `405` for non-POST methods.
- `429` for abuse/rate-limit failures if rate limiting is added.

Do not make telemetry endpoints authentication-dependent. The event contract must stay anonymous
and must not attach auth/profile state even when a visitor is logged in.

### Allowed Event Contract

Use the existing frontend taxonomy as the server allowlist. The backend must reject any event name
or payload key not listed here.

| Event | Required keys | Optional keys |
| --- | --- | --- |
| `page_view` | `routeKey` | `locale` |
| `cta_clicked` | `surface`, `targetId` | `targetRouteKey` |
| `nav_item_clicked` | `itemId`, `targetRouteKey` | none |
| `theme_mode_changed` | `mode` | none |
| `palette_changed` | `palette` | none |
| `language_changed` | `language` | none |
| `chat_widget_opened` | `surface` | none |
| `chat_widget_closed` | `surface` | none |
| `chat_preset_question_clicked` | `presetId` | none |
| `docs_anchor_clicked` | `anchorId` | none |
| `certification_verify_clicked` | `credentialId`, `targetId` | none |
| `contact_intent_clicked` | `targetId` | none |

Allowed value sets:

- `routeKey` / `targetRouteKey`: `home`, `docs`, `certifications`, `deepseek_chat`, `login`,
  `register`, `profile`, `not_found`, `server_error`.
- `locale` / `language`: `zh-CN`, `en`.
- `mode`: `light`, `dark`.
- `palette`: `default`, `aurora`, `forest`.
- `presetId`: `who_is_renda`, `personalweb_proof`, `cloud_native_evidence`,
  `certification_context`, `recruiter_summary`.
- Other ID fields must be short controlled identifiers matching the frontend safe identifier rule.

### Rejected Data

The backend validator must reject:

- Visitor-entered text, chat messages, prompts, generated answers, contact form content, profile
  fields, auth identifiers, user IDs, names, emails, phone numbers, cookies, tokens, passwords,
  secrets, raw user-agent strings, explicit IP address fields, full URLs, query strings, private
  paths, backend hostnames, operational logs, and private production details.
- Payload keys matching sensitive names such as `message`, `prompt`, `body`, `content`, `email`,
  `phone`, `name`, `token`, `cookie`, `session`, `user`, `uid`, `auth`, or `profile`.
- Values that look like emails, phone numbers, full URLs, query strings, private paths, or long
  free-form strings.

### Persistence Shape

If aggregate-only telemetry is later approved, prefer one daily aggregate table:

```sql
CREATE TABLE visitor_event_daily_counts (
  event_date DATE NOT NULL,
  event_name TEXT NOT NULL,
  dimension_key TEXT NOT NULL,
  dimensions JSONB NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (event_date, event_name, dimension_key)
);
```

`dimensions` may contain only sanitized controlled fields from the allowed payload. `dimension_key`
is a deterministic hash or joined key derived from the sanitized dimensions. Do not store a raw
event row before incrementing the aggregate.

### Retention

- No-Go current state: no telemetry storage, so no telemetry retention job is needed.
- Future aggregate-only state: keep aggregate rows for at most 90 days.
- Future raw event storage: not recommended; if a later owner explicitly overrides this, raw rows
  must be capped at 30 days and require a separate privacy review before implementation.

### Privacy Note

No visible privacy note is required while visitor events remain frontend-local/no-op.

If aggregate transport ships later, add a visible public privacy note before enabling transport. The
note should state that the site records only first-party aggregate interaction counts using
controlled event IDs and does not record typed messages, chat transcripts, generated answers,
contact form contents, auth/profile identifiers, emails, phones, cookies, tokens, full URLs, query
strings, raw IP fields, or raw user-agent strings.

## Validation Plan For A Future Go Slice

Backend validation:

- Unit tests for event allowlist, payload key allowlist, sensitive key rejection, sensitive value
  rejection, aggregate increment behavior, and rate-limit behavior.
- `python -m compileall app.py app_auth.py db.py mailer.py models.py security_policy.py`
- `ruff check .`
- `black --check .`
- `pre-commit run --all-files`
- Local curl checks for accepted and rejected events.

Frontend validation if transport is wired later:

- Focused tests proving only normalized events are sent.
- Tests proving preset telemetry remains `{ presetId }` only.
- Tests proving typed chat input, generated answers, contact form content, auth/profile data, full
  URLs, query strings, cookies, and tokens are never sent.
- `npm run sync`
- `npm run lint`
- `npm run typecheck`
- `npm run check`
- `npm run test:coverage`
- `npm run smoke:browser`

## Deployment Requirements For A Future Go Slice

A future aggregate-only implementation would require:

- Backend code and docs commit.
- A PostgreSQL migration or schema update.
- A narrow backend deployment to the CloudChat service.
- Restart of only `cloudchat.service`.
- No Nginx change for the route shape above unless the path, buffering, caching, or rate-limit
  behavior changes.
- A separate frontend commit to enable transport only after the backend endpoint is verified.

## Rollback Plan For A Future Go Slice

- Disable frontend transport first so no browser sends telemetry.
- Keep the backend endpoint returning `204` or reject all requests while the frontend rollback
  propagates.
- Drop or ignore aggregate rows after the retention window.
- Revert backend code and migration only after confirming no frontend bundle is still posting
  events.
- No Chat Widget iframe protocol rollback should be needed because telemetry must remain outside
  the iframe ready protocol.
