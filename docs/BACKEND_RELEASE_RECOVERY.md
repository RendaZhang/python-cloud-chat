# Backend Release Recovery Contracts

## Prepared, Not Active

Slice 18.3.1 adds pure standard-library contracts under `scripts/backend_release/`.
They do not deploy, install packages, write a journal, start processes, call systemd,
contact the network, import Flask, or touch application data. Existing production
delivery and the canonical service unit remain unchanged. Valid input records and
passing unit tests do **not** prove working recovery or production readiness.

The current production workflow still updates its checkout and environment and can
restore a replaced service unit. That is not complete code/environment recovery.
The prepared contracts describe the inputs and decisions for a later, separately
validated replacement. Do not run a production deployment merely to exercise them.

## Contract Ownership

| Module | Pure responsibility |
| --- | --- |
| `contracts.py` | Strict bounded JSON, explicit fixture roots, regular-file/code inventories, interpreter/platform/package declarations, fixed environment paths, wheel evidence structure, release and request identities. |
| `decisions.py` | Compare requested inputs with accepted runtime, environment-reuse decisions, protected environment references and initial-adoption planning. |
| `unit.py` | Render a string from the exact reviewed canonical policy using only validated paths and bounded candidate substitutions. |
| `state.py` | In-memory ownership, phase, evidence and deadline decisions; no durable state or recovery executor. |

All path-bearing operations require explicit fixture roots. Lexical checks reject
escapes and shell/systemd interpolation characters; known live root prefixes are
excluded. Constructors and queries create no directories. These checks cannot prove
that a real filesystem has safe ownership, modes, symlink targets or available space.
That proof belongs to a later host adapter, not a relaxed fixture-root check.

Records reject duplicate JSON keys, unknown/missing fields, non-standard/non-finite
numbers, booleans/floats where integers are required, oversized inventories, duplicate
files/packages, file/directory collisions, special files and unsafe modes. Declared
code excludes hidden/private/runtime-state paths. Only controlled failure codes are
kept; no raw errors, environment values, chat content or visitor data are needed.

Runtime inventories are order-independent. A release identity binds source SHA,
runtime digest, full environment identity, canonical/rendered unit digests, helper
digest and request/run/attempt/generation. Sorting an equivalent inventory must not
change its identity. These are declarations of evidence, not cryptographic proof
that the corresponding bytes are installed or executing.

## Source Is Not the Serving Release

`ChangeDecision` keeps checkout, serving and requested source SHAs distinct.
Classification compares the requested runtime and environment with the **accepted**
release, not just the latest checkout. A documentation commit following a failed
runtime update must not hide the still-pending code difference.

Known documentation/test/helper/workflow paths plus unchanged accepted runtime can
plan source synchronization without restart. Explicit force restart requires a
transaction. Unknown runtime assets, schema/runtime-pin changes, canonical-policy
changes and installed-unit drift require review. This foundation does not authorize
any of those changes or execute the planned source synchronization.

After a later rollback the checkout may remain at the failed source SHA while the
accepted code/environment/unit triple serves. Do not use reset/force-push to conceal
that distinction. A failed transaction remains failed even after recovery succeeds.

## Fixed Environments and First Adoption

Environment reuse requires equal requirements, interpreter binary/base path, reviewed
Python version and ABI, platform, package inventory, and fixed final path, plus explicit
inventory and pip-check evidence. Equal requirements alone are insufficient.

Prepared environments are named at their final absolute fixture paths before use.
The legacy environment is explicitly adopted at its original path; it is not copied
or renamed. Package evidence does not make an installed virtualenv relocatable.

First adoption must precede source synchronization: capture the existing source,
retain its original environment and prepare the equivalent immutable code snapshot
and rendered unit. Until adoption is accepted, source-sync permission remains false,
including after a failed/recovered adoption. Later Linux proof must demonstrate the
original source/unit stay usable if this first transaction fails.

The renderer pins the current canonical policy digest. Live rendering changes only
WorkingDirectory and the absolute Gunicorn entrypoint. Candidate rendering may also
use a unique runtime/HOME, the alternate loopback port, no live StateDirectory,
Restart=no and RuntimeMaxSec=35. Every other directive is preserved, including the
locked non-root identity, capabilities, filesystem restrictions, two workers,
250M/300M memory limits, TasksMax=128 and the 90-second stop policy. The real canonical
unit is not modified, installed or verified by this renderer.

## Wheel Evidence Is Structural Only

Wheel records declare requirements/interpreter/platform identity, bounded filenames,
project/version, byte counts, hashes and an optional offline-proof artifact digest.
The parser rejects duplicate projects/filenames, unsupported file kinds and bounds.
It does not resolve dependencies, interpret wheel tags as compatibility proof, open
archives, validate wheel contents, install packages or authenticate a proof artifact.

Before production can use a replacement environment, matching Linux/CPython tests
must prove the complete exact-version wheel closure, hashes, native imports and a
network-disabled installation at the final path. Missing native wheels, incomplete
closure or incompatible tags are blockers, not permission to compile or download
packages during recovery. No such proof or installation occurs in this slice.

## Transition and Deadline Decisions

The state model supports prepared, activating, accepted, failed, recovered, uncertain
and degraded records. Owner request/run/attempt/generation must match. Later-generation
records reject stale owners. Activation starts one clock; retries cannot restart it.
Acceptance is the modeled commit point and cannot be undone by a late guard callback.
Recovery requires the baseline identity and the same unit/isolation/internal/public
checks as forward acceptance. Uncertain/degraded states do not claim a running release.

The proposed deadline is **270 seconds forward + 210 seconds reserved recovery =
480 seconds total**. Forward acceptance at/after its deadline and recovery success
at/after the total deadline are rejected. This is decision logic, not a measured
service guarantee. A later durable adapter must fence actual lock owners and pending
jobs, survive caller loss, and prove the full serial stop/candidate/stop/start/recover
sequence including 90-second drains and cleanup. No overlapping app instances,
zero-downtime claim, five-minute promise or persistent recovery daemon is implied.

## Unproven Resources and Retention Conflict

The proposed disk envelope remains 1,280 MiB: two environments at 384 MiB each,
64 MiB code/unit/metadata/helper, 256 MiB wheels, 128 MiB workspace and 64 MiB scoped
caches. Preparation proposes 128 MiB temporary-process budget plus 128 MiB physical
reserve. These figures are **unproven** on the target and are not admission results.
Cold application/rollback memory, total process peaks, disk/inode high-water and
host reserve still require measurements. Swap is not additional physical headroom.

Current, previous and active references are protected. Identical references may share
one fixed environment; conflicting evidence at the same path is rejected. When two
different protected environments already exist, a third distinct candidate is refused.
No previous environment is evicted, moved or counted as workspace. General repeated
dependency-changing rollout is therefore **not solved** under the current two-env
contract; changing capacity or retention requires a separate reviewed decision.

## Validation and Remaining Gates

Use the repository's existing pinned Python environment:

```bash
venv/bin/python -m unittest discover -s tests -p 'test_backend_release_*.py'
venv/bin/python -m unittest discover -s tests
```

Focused tests use synthetic declarations and temporary directories. An isolated import
test refuses filesystem mutations, network sockets and child-process launches from
the modules. Unit rendering tests compare every untouched policy line. Existing
application tests remain separate and mock external boundaries as documented in
[TESTING.md](TESTING.md).

Future gates are separate: durable backend lifecycle adapter and real Linux/systemd
fault tests; complete offline wheel/install proof; measured deadline/resource proof;
branch-only workflow integration; and explicitly approved production adoption after
frontend production acceptance. Current fixture checks must not be reported as any
of those results. There is no production CLI or automatic recovery in this foundation.
