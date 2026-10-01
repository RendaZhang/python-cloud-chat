# Backend Release Recovery Contracts

## Prepared, Not Active

Slice 18.3.1 adds pure standard-library contracts under `scripts/backend_release/`.
Slice 18.3.2a adds a separate, explicit temporary-fixture state store. The pure modules
remain side-effect free; only the fixture store performs filesystem operations.
Neither layer deploys, installs packages, starts application processes, calls systemd,
contacts the network, imports Flask, or touches application data. Existing production
delivery and the canonical service unit remain unchanged. Passing fixture tests do
**not** prove application recovery or production readiness.

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
| `records.py` | Pure, bounded versioned serialization of transaction, ownership, clock, source/serving and reserved-inode identities. |
| `store.py` | Explicit POSIX temporary-fixture initialization, bounded locks, compare-and-swap persistence and known-alias cleanup; no host adapter or production CLI. |

All path-bearing operations require explicit fixture roots. Lexical checks reject
escapes and shell/systemd interpolation characters; known live root prefixes are
excluded. Constructors and queries create no directories. These checks cannot prove
that a real filesystem has safe ownership, modes, symlink targets or available space.
That proof belongs to a later host adapter, not a relaxed fixture-root check.

The fixture store additionally walks directory descriptors without following symlinks,
pins the directory chain, and checks actual ownership/modes and inode/link identities
at read, lock and commit boundaries. It accepts an existing private 0700 directory
under supported POSIX temporary prefixes only; callers supply its canonical path.
Regular record files are owned 0600 files. Unexpected symlinks, devices, FIFOs,
slot/lock replacements or extra hardlinks are refused. This is not protection against
a malicious process with the same account/root privileges or a general host sandbox.

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

## Durable Fixture State

Construction validates the existing directory but creates nothing. `read()` and
`deadline()` never initialize, repair or clean files. Only explicit `initialize()`
reserves an empty lock file and two record-slot inodes, then establishes `state.json`.
There is no default root and no executable production command.

The version-1 record binds both releases, checkout/serving/accepted identities,
request/run/attempt/generation, phase/failure, one clock context, revision/predecessor
digest, root/lock identities and both fixed slot identities. Nested release parsing
uses the existing strict contracts. The entire combined record still has the original
64 KiB limit. A checksum detects corruption but is not authentication. Status never
chooses the highest slot revision or invents an authority when `state.json` is missing.

There is one authoritative name: `state.json`, a hardlink to one reserved slot.
Within the permanent exclusive lock, a writer re-reads and checks the exact expected
revision/digest and owner before calculating the transition. It rewrites only the
inactive slot, completes short writes, fsyncs that file, links a same-directory
`pending.json` alias to the known inode, atomically replaces `state.json`, then fsyncs
the directory. The replacement is the acceptance decision; successful return requires
directory-sync confirmation too. An ambiguous replacement or subsequent failure raises
`DurabilityUncertain`,
never a claim that the old state still serves. Terminal acceptance remains protected
from stale failure callbacks. Recovered records retain the original failed outcome.

Readers hold a bounded shared lock, so a subsequent writer cannot reuse a slot beneath
an open reader. Writers use a bounded exclusive lock, re-read after acquiring it and
never unlink the lock or kill its holder. Waits default to 250 ms and are capped at
2,000 ms; a stopped holder causes `LockBusy`, not takeover. This is local POSIX flock
coordination, not distributed ownership or actual process/cgroup fencing.

An initialized record already owns both slot inodes before any later write starts.
After a writer crash, truncated/partial inactive data can be overwritten safely.
Under the same exclusive lock, cleanup may remove only a `pending.json` alias whose
inode and exact link count match those already-durable slot identities. Unknown files
are preserved and refused. There is no per-write ownership sidecar or ownership-creation
window to strand future writes. The two slots allocate at most 128 KiB of logical record
data total; the authoritative and pending hardlink names do not allocate extra copies.
Filesystem block/inode overhead is not a production disk-capacity measurement.

Initial empty-fixture bootstrap is different: interruption before the first authoritative
record exists leaves unproven artifacts. Read fails and re-initialization refuses rather
than sweeping them or selecting a candidate slot. The test owner may discard that exact
temporary fixture and create a fresh one. This limitation is acceptable only before any
application activation/source synchronization. Later lifecycle work must finish bootstrap
and establish its durable baseline **before** stopping a live service.

The clock context is an explicit caller-supplied boot/clock identity, not a boot-ID probe.
Reopening preserves activation time. Changed/unknown context or backwards/exhausted time
cannot authorize acceptance/recovery or reset the clock. A later host adapter must source
and validate real clock evidence. The proposed 270+210-second policy is unchanged and
unmeasured; fixture lock timings are not a service recovery guarantee.

## Validation and Remaining Gates

### Offline Preparation Capacity Checkpoint

The prepared split is a feasibility experiment, not a release builder. The manual
owned-feature dispatch has two sequential disposable Ubuntu 24.04 jobs, each with
an independent read-only setup-python CPython 3.13.14 input. The producer performs
normal pip binary-only resolution of all 73 unchanged pins; the fresh consumer
receives the artifact before a genuinely offline final-path installation. Local
portable tests do not exercise either Linux job. No new capacity result is claimed.

`preparation_probe.py` owns the experiment and `preparation_artifact.py` owns its
bounded transport. Each role verifies its own base binary/path/ABI and ensurepip
seed; sharing compatible wheels does not require equal producer/consumer binary
digests or paths. No base copy, relocated venv or change to the pure contracts/store.

The producer's approved experimental preparation budget is 256 MiB/no swap and
512 MiB scratch (256 wheels/transfer + 128 workspace + 64 cache + 64 metadata).
The consumer keeps 128 MiB/no swap, with the separate proposed 128 MiB host reserve
unchanged. Within those totals, reserve **32 MiB** for serial external systemd-run /
systemctl child RSS and cap the measured service at **224 / 96 MiB** respectively.
The previous control-child measurement was 21,106,688 bytes; fork/exec may include
inherited Python RSS. Do not subtract it or assume an 8 MiB allowance would pass.
The new partition is unmeasured, not an assertion that either installer fits.
The serial child RSS gate must pass independently; it is a conservative separate
high-water, not a simultaneous aggregate measurement or a cgroup hard bound.

The service contains actual preparation control, sampler, receiver/TLS, hashing,
extraction, base reads, seed/install/check/native children and charged file cache.
The outside Python observer only launches/stops the owned unit and collects CI
evidence; its RSS is separately reported. CI setup/quality, runner/system manager
baseline and artifact upload relay are not inside the service. Their aggregate
memory is not measured or claimed bounded. A future target launch adapter, shared
kernel/cache costs and fresh host admission remain unproved; this is not production
aggregate acceptance. Unknown cleanup ownership refuses and preserves the fixture.

The producer builds one bounded ZIP and an exact 73-wheel manifest, then the
existing upload-artifact action publishes it as a CI-only relay (one-day retention).
The consumer does **not** use download-artifact or a pre-staged copy. A measured
stdlib child uses the same-run artifact ID/digest and ephemeral `actions: read`
token, verifies REST metadata/run/SHA, follows one HTTPS storage redirect without
forwarding Authorization, streams at most 128 MiB, checks the outer hash and safely
unwraps it. It never logs token values, signed URLs or server error bodies. Changed
storage hosts, expired/missing artifacts, corrupt bytes or unexpected members fail
closed; no persistent credentials or deployment secrets are involved.
See [GitHub artifact downloads](https://docs.github.com/en/rest/actions/artifacts#download-an-artifact).

The inner manifest binds source, requirements, run/attempt, producer tool/runtime/
platform/seed and every filename/root-metadata identity/size/hash. The consumer
independently rehashes and reparses all wheels. Archive links, path escapes,
duplicates, unexpected members and expansion bounds refuse before installation.
Hashes are integrity checks, not independent publisher authentication. All 73
hash-pinned entries are explicit; `--no-deps` suppresses traversal only, not closure
validation. Full producer resolution, exact installed inventory plus bundled pip,
pip check and existing native imports remain required. Real network namespaces cover
seed, install, pip check and native validation; no application import is allowed.
See [pip download](https://pip.pypa.io/en/stable/cli/pip_download/) and
[pip hash checking](https://pip.pypa.io/en/stable/topics/secure-installs/).

Deadlines remain download 300s, ingress 120s, base/network 10s each, seed 60s,
install 180s, pip-check/native 30s each, unit 650s/stop 10s and each job 20 minutes.
The small JSON receipts retain cumulative current/peak/events/keyed memory.stat,
per-stage time, actual sampling gaps and sampled allocated bytes/files/inodes.
Stage ended does not mean passed. Never reset peaks, subtract cache, or replace a
larger live measurement with a smaller post-exit value. Zero OOM is not enough.
The finite `Type=exec` service saves/fsyncs live receipts, checks for remaining
owned writers, removes its known incomplete paths and saves a final live snapshot
before returning. It does not use `RemainAfterExit`; the waiting launcher can finish
on normal exit. The CI observer then checks/stops the owned unit and proves no owned
processes remain. Timeout kills/reaps the launcher and stops the unit; uncertain
cleanup preserves the fixture. Separate post-exit observations never replace live
peaks. Portable tests cover this ordering but are not a Linux systemd run.

Each name in the probe's `STAGES` allowlist can occur once per role. Producer stages
include packaging; consumer stages include ingress and artifact verification. Missing
stages are not executed, not implicitly successful. Nominal 100 ms sampling also
records actual gaps, sample counts, start/latest readings and the stat breakdown at
sampled current high-water. These are not exclusive per-stage peaks or simultaneous
atomic snapshots. Missing required metrics fail closed.

The bounded diagnostic pass selects one root distribution `.dist-info/METADATA`,
not nested vendored metadata. It retains the 1 MiB metadata bound and rejects missing,
ambiguous or duplicated root entries, duplicate identity headers, project duplicates,
and filename/directory/header/pin identity mismatches. The receipt reports the actual
public wheel filename and member counts, with at most two root names and three nested
name samples per diagnostic (160 characters each), and at most eight nested-archive
examples plus the last archive. Metadata contents are not retained. This is still a
checkpoint validator, not a complete immutable archive validator.

After binary download, metadata diagnosis is retained before the measured resource
gate, so an archive defect and memory pressure can be distinguished. Any observed
current/peak above the role's service partition, swap usage or OOM fails before seed/install;
the remaining stages cannot proceed. Limits are also checked at later stage boundaries
and finalization. Diagnosis is not permission to raise a budget or change a pin.
Both previous checkpoints failed before install; neither their partial download nor
this unexecuted split establishes offline installation or capacity acceptance.
See the [wheel specification](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
and [cgroup v2 memory semantics](https://docs.kernel.org/admin-guide/cgroup-v2.html).

Disk samples are not quotas. Archive/expanded copies share the existing wheel slot;
the outer ZIP is removed before inner expansion, never after granting extra space.
The consumer keeps the original 1280 MiB total and component budgets, with zero
protected environments explicitly disclosed. Actual two-environment occupancy,
third-distinct refusal under load, reuse, immutable publication and production
capacity remain later gates. No installed environment is uploaded or retained as a
portable artifact. A missing wheel artifact refuses new preparation, not a fallback
online install or change to accepted rollback environments.
Failure stops/reaps owned writers before verified incomplete-path removal. Unknown
ownership or a killed owner preserves evidence rather than sweeping from the
external observer. Public producer bundle and bounded sanitized receipts remain
for CI relay/runner disposal; receipts retain seven days, not a recovery promise.
Any failure fails the job; no automatic tuning retry or increased limits.

The existing quality and production deployment jobs are unchanged. The proof runs
only for the owned feature's manual dispatch;
master dispatch cannot run it and feature dispatch cannot deploy. Root planning
documents and production access remain outside this checkpoint.

Use the repository's existing pinned Python environment:

```bash
venv/bin/python -m unittest discover -s tests -p 'test_backend_release_*.py'
venv/bin/python -m unittest tests.test_backend_release_store tests.test_backend_release_store_process
venv/bin/python -m unittest discover -s tests
```

Focused tests use synthetic declarations and temporary directories. An isolated import
test refuses filesystem mutations, network sockets and child-process launches from
the modules. Unit rendering tests compare every untouched policy line. Existing
application tests remain separate and mock external boundaries as documented in
[TESTING.md](TESTING.md).

Real owned subprocess tests run on macOS and Linux without platform skips. Pipe barriers
place failures at inactive-slot truncate, partial/full write, file fsync, alias creation,
atomic replacement, directory fsync and interrupted alias cleanup. Tests then reopen,
record failure/recovery and start another generation. They also cover competing writers,
shared readers, stale callbacks, stopped/killed lock holders and incomplete initial
bootstrap. All child processes are collected and only test-owned temporary roots are
removed. Injected write/fsync failures, invalid records, clock mismatch and path/alias
substitution tests complement the process cases. CI prints executed process cases and
collected-child counts. These are process-crash fixtures, **not power-loss tests** or
evidence about real systemd, application availability or production filesystems.

Future gates are separate: durable backend lifecycle adapter and real Linux/systemd
fault tests; complete offline wheel/install proof; measured deadline/resource proof;
branch-only workflow integration; and explicitly approved production adoption after
frontend production acceptance. Current fixture checks must not be reported as any
of those results. There is no production CLI or automatic recovery in this foundation.
