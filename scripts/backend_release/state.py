"""In-memory transition proposals, not a durable journal or a recovery executor."""

from dataclasses import dataclass, replace

from .contracts import Release, RequestIdentity, boolean, digest, integer, require

FORWARD_SECONDS = 270
RECOVERY_SECONDS = 210
TOTAL_SECONDS = FORWARD_SECONDS + RECOVERY_SECONDS
FAILURES = frozenset(
    {"start", "health", "isolation", "timeout", "caller_lost", "uncertain"}
)


@dataclass(frozen=True)
class Checks:
    observed_release_digest: str
    unit: bool
    isolation: bool
    internal_health: bool
    public_health: bool

    def __post_init__(self):
        digest(self.observed_release_digest)
        for value in (
            self.unit,
            self.isolation,
            self.internal_health,
            self.public_health,
        ):
            boolean(value)

    def ready_for(self, release: Release) -> bool:
        return self.observed_release_digest == release.identity_digest and all(
            (self.unit, self.isolation, self.internal_health, self.public_health)
        )


@dataclass(frozen=True)
class Transaction:
    baseline: Release
    requested: Release
    source_checkout_sha: str
    kind: str
    phase: str = "prepared"
    started_at: int | None = None
    last_at: int = 0
    failure: str | None = None

    def __post_init__(self):
        require(
            type(self.baseline) is Release and type(self.requested) is Release,
            "Invalid release",
        )
        require(
            self.baseline.environment.fixtures == self.requested.environment.fixtures,
            "Fixture roots changed",
        )
        require(
            self.requested.request.generation > self.baseline.request.generation,
            "Generation is not newer",
        )
        require(
            self.requested.request.request_id != self.baseline.request.request_id,
            "Request ID reused",
        )
        digest(self.source_checkout_sha, 40)
        require(self.kind in ("release", "adoption"), "Unknown transaction kind")
        require(
            self.phase
            in (
                "prepared",
                "activating",
                "accepted",
                "failed",
                "recovered",
                "uncertain",
                "degraded",
            ),
            "Unknown phase",
        )
        integer(self.last_at, 0)
        if self.started_at is not None:
            integer(self.started_at, 0)
            require(self.started_at <= self.last_at, "Clock moved backwards")
        require(
            self.failure is None
            or (type(self.failure) is str and self.failure in FAILURES),
            "Unknown failure code",
        )
        require(
            (self.phase in ("failed", "recovered", "uncertain", "degraded"))
            == (self.failure is not None),
            "Inconsistent failure outcome",
        )
        require(
            self.phase == "prepared"
            or self.started_at is not None
            or self.phase == "failed",
            "Missing activation clock",
        )
        require(
            self.phase != "prepared" or self.started_at is None,
            "Prepared phase already activated",
        )
        if self.phase in ("accepted", "recovered"):
            limit = FORWARD_SECONDS if self.phase == "accepted" else TOTAL_SECONDS
            require(
                self.last_at - self.started_at < limit, "Terminal deadline exhausted"
            )
        if self.kind == "adoption":
            require(
                self.source_checkout_sha
                == self.baseline.code.source_sha
                == self.requested.code.source_sha,
                "Source advanced before adoption",
            )
            require(
                self.baseline.environment.origin == "legacy",
                "Legacy environment required",
            )
            require(
                self.baseline.environment == self.requested.environment,
                "Legacy environment changed",
            )
            require(
                self.baseline.code.runtime_digest == self.requested.code.runtime_digest,
                "Adoption changed code",
            )
            require(
                self.baseline.policy_digest == self.requested.policy_digest,
                "Adoption changed policy",
            )

    @property
    def owner(self) -> RequestIdentity:
        return self.requested.request

    @property
    def accepted(self) -> Release:
        return self.requested if self.phase == "accepted" else self.baseline

    @property
    def serving(self) -> Release | None:
        if self.phase == "accepted":
            return self.requested
        if self.phase in ("prepared", "recovered"):
            return self.accepted
        if self.phase == "failed" and self.started_at is None:
            return self.baseline
        return None


def prepare(
    accepted: Release,
    requested: Release,
    *,
    source_checkout_sha: str,
    kind: str = "release"
) -> Transaction:
    return Transaction(accepted, requested, source_checkout_sha, kind)


def _fence(state: Transaction, owner: RequestIdentity, now: int):
    require(
        type(state) is Transaction and type(owner) is RequestIdentity, "Invalid owner"
    )
    require(owner == state.owner, "Stale transaction owner")
    integer(now, 0)
    require(now >= state.last_at, "Clock moved backwards")


def deadline_decision(state: Transaction, owner: RequestIdentity, now: int) -> str:
    _fence(state, owner, now)
    if state.phase in ("accepted", "recovered", "prepared") or state.started_at is None:
        return "none"
    elapsed = now - state.started_at
    if elapsed >= TOTAL_SECONDS:
        return "fail_closed"
    if elapsed >= FORWARD_SECONDS or state.phase in ("failed", "uncertain", "degraded"):
        return "recover"
    return "continue"


def transition(
    state: Transaction,
    owner: RequestIdentity,
    event: str,
    *,
    now: int,
    checks: Checks | None = None,
    failure: str | None = None
) -> Transaction:
    _fence(state, owner, now)
    require(
        event in ("activate", "accept", "fail", "recover", "uncertain", "degrade"),
        "Unknown event",
    )
    require(
        state.phase not in ("accepted", "recovered"),
        "Terminal outcome cannot be rewritten",
    )
    if event == "activate":
        require(state.phase == "prepared", "Activation already started")
        return replace(state, phase="activating", started_at=now, last_at=now)
    if event == "accept":
        require(state.phase == "activating", "Cannot accept this phase")
        require(now - state.started_at < FORWARD_SECONDS, "Forward deadline exhausted")
        require(
            type(checks) is Checks and checks.ready_for(state.requested),
            "Acceptance evidence incomplete",
        )
        return replace(state, phase="accepted", last_at=now)
    if event == "recover":
        require(
            state.phase in ("failed", "uncertain", "degraded"), "Failure not recorded"
        )
        require(
            state.started_at is not None and now - state.started_at < TOTAL_SECONDS,
            "Recovery deadline exhausted",
        )
        require(
            type(checks) is Checks and checks.ready_for(state.baseline),
            "Recovery evidence incomplete",
        )
        return replace(state, phase="recovered", last_at=now)
    if event in ("uncertain", "degrade"):
        require(state.started_at is not None, "Not activated")
        return replace(
            state,
            phase="uncertain" if event == "uncertain" else "degraded",
            failure=state.failure or "uncertain",
            last_at=now,
        )
    require(
        type(failure) is str and failure in FAILURES,
        "Controlled failure reason required",
    )
    return replace(state, phase="failed", failure=state.failure or failure, last_at=now)


def source_sync_allowed(state: Transaction) -> bool:
    require(type(state) is Transaction, "Invalid transaction")
    if state.kind == "adoption":
        return state.phase == "accepted"
    return state.phase in ("prepared", "accepted", "recovered") or (
        state.phase == "failed" and state.started_at is None
    )
