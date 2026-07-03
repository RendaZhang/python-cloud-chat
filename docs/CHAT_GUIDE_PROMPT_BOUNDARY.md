<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Chat Guide Prompt Boundary](#chat-guide-prompt-boundary)
  - [Purpose](#purpose)
  - [Current Status](#current-status)
  - [Public Source Package](#public-source-package)
  - [Prompt Builder Contract](#prompt-builder-contract)
  - [Privacy Boundary](#privacy-boundary)
  - [Live API Boundary](#live-api-boundary)
  - [Validation](#validation)
  - [Next Slice Handoff](#next-slice-handoff)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Chat Guide Prompt Boundary

- **Last Updated**: July 03, 2026, 12:49 (UTC+08:00)
- **Scope**: Slice 12.2 backend-owned public knowledge package and pure Chat Guide prompt builder.
- **Status**: Implemented as unused backend code. Not wired into live `/deepseek_chat`.

## Purpose

The Chat Guide should answer public questions about Renda Zhang, PersonalWeb, certifications,
work/education evidence, cloud-native credibility, and site navigation from public sources only.
Slice 12.2 moves the source-bounded answer policy into backend-owned code before any live API
transport or frontend request-shape change exists.

This document describes the backend prompt boundary added in `chat_guide_prompt.py`.

## Current Status

Implemented now:

- Controlled preset IDs aligned with the frontend:
  `who_is_renda`, `personalweb_proof`, `cloud_native_evidence`, `certification_context`, and
  `recruiter_summary`.
- Public source categories and localized source labels.
- Source-bounded public facts for identity, PersonalWeb proof, cloud-native evidence,
  certification context, recruiter scanning, work/education evidence, and navigation.
- Refusal and unknown-answer rules for private, unsupported, and prompt-injection questions.
- `build_chat_guide_prompt(...)`, a pure prompt builder that accepts:
  - the current visitor question;
  - an optional controlled preset ID;
  - an optional locale/language hint.
- Focused standard-library unit tests in `tests/test_chat_guide_prompt.py`.

Not implemented now:

- No route, request body, streaming response, session, frontend, Nginx, database, Redis, telemetry,
  dependency, runtime, or production service behavior change.
- No RAG/vector retrieval, crawler, CMS, external search dependency, or persistent public knowledge
  store.

## Public Source Package

The backend source package allows only public source categories:

| Category | Use |
| --- | --- |
| `homepage` | Visible homepage positioning, work/education summary, proof CTAs, and public contact intent surfaces. |
| `docs` | `/docs/` rendered project proof and README-backed technical documentation. |
| `frontend_docs` | Public frontend architecture, testing, SEO/GEO, directory ownership, style, and Chat Widget protocol docs. |
| `backend_docs` | Public backend API and testing docs for high-level backend behavior. |
| `certifications` | `/certifications/` visible credential context. |
| `llms` | `llms.txt` public AI/search summary. |
| `metadata` | Public metadata, sitemap, and JSON-LD aligned with visible content. |
| `public_github_docs` | Public repository documentation intentionally linked from the site. |

The package intentionally does not include private server paths, environment values, logs, database
records, Redis keys, production credentials, chat transcripts, contact submissions, auth/profile
records, or visitor-entered text from other users.

## Prompt Builder Contract

`build_chat_guide_prompt(question, preset_id=None, locale=None)` returns a `ChatGuidePrompt` value:

- `prompt`: model-facing instructions and public source package text;
- `locale`: normalized to `en` or `zh`;
- `preset_id`: the controlled preset ID if accepted, otherwise `None`;
- `source_labels`: controlled source labels included in the prompt;
- `used_unknown_preset_fallback`: `True` only when a caller supplied an unknown preset ID.

Unknown preset IDs fail closed by falling back to the generic public-site guide prompt. The unknown
ID is not echoed into the model-facing prompt.

The prompt instructs the model to treat the visitor question as data, not as instructions that can
override the public-content-only boundary.

## Privacy Boundary

The prompt builder is pure. It does not:

- write logs;
- write browser or server storage;
- mutate Flask sessions;
- emit telemetry events;
- call model APIs;
- call Redis, PostgreSQL, SMTP, Nginx, or third-party analytics;
- read cookies, auth/profile identifiers, IP fields, raw user-agent strings, or request headers.

The prompt text may include the current visitor question because a later Chat Guide integration
will need to send that question to the model. It must not be reused as visitor telemetry or stored
as an analytics event.

## Live API Boundary

The live chat endpoint remains unchanged in Slice 12.2:

- `/deepseek_chat` still accepts `{ "message": "..." }`.
- Streaming still returns newline-delimited JSON chunks with a `text` field.
- The Flask session chat history behavior is unchanged.
- `app.py` does not import `chat_guide_prompt.py`.
- Frontend request payloads and the Chat Widget iframe protocol are unchanged.

The next integration slice should explicitly decide the guide-mode request shape before using this
prompt builder in live traffic.

## Validation

Focused tests:

```bash
python -m unittest discover -s tests
```

Repository checks:

```bash
python -m compileall app.py app_auth.py db.py mailer.py models.py chat_guide_prompt.py tests
ruff check .
black --check .
pre-commit run --all-files
```

## Next Slice Handoff

The next slice should wire an explicit Chat Guide mode from frontend to backend only after this
backend prompt boundary is stable. Default chat behavior should remain unchanged when guide mode is
absent, and preset telemetry should remain controlled ID-only/no-op unless a later privacy decision
changes transport.
