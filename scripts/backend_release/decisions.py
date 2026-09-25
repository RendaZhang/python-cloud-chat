"""Pure planning decisions; a valid declaration is not production admission."""

from dataclasses import dataclass

from .contracts import (
    EnvironmentEvidence,
    Release,
    RUNTIME_FILES,
    boolean,
    digest,
    path,
    require,
)

PROPOSED_DISK_MIB = 1280
PROPOSED_PREPARATION_MIB = 128
PHYSICAL_RESERVE_MIB = 128


@dataclass(frozen=True)
class ChangeDecision:
    action: str
    source_checkout_sha: str
    serving_source_sha: str
    requested_source_sha: str
    reason: str


def classify(
    accepted: Release,
    requested: Release,
    *,
    source_checkout_sha: str,
    changed_paths: tuple[str, ...],
    observed_unit_digest: str,
    force_restart: bool = False,
) -> ChangeDecision:
    require(type(accepted) is Release and type(requested) is Release, "Invalid release")
    require(
        accepted.environment.fixtures == requested.environment.fixtures,
        "Fixture roots changed",
    )
    digest(source_checkout_sha, 40)
    digest(observed_unit_digest)
    boolean(force_restart)
    require(
        type(changed_paths) is tuple and len(changed_paths) <= 512, "Invalid changes"
    )
    for value in changed_paths:
        path(value, absolute=False)
    require(len(set(changed_paths)) == len(changed_paths), "Duplicate changed path")

    reason = ""
    for value in changed_paths:
        if value in {"schema.sql", ".python-version", ".mise.toml"}:
            reason = "schema_or_runtime_review"
            break
        if not (
            value in RUNTIME_FILES
            or value
            in {
                "requirements.txt",
                "deploy/cloudchat.service",
                "README.md",
                "AGENTS.md",
                "LICENSE",
                ".gitignore",
                ".gitattributes",
                ".pre-commit-config.yaml",
                ".github/workflows/backend-ci.yml",
                "scripts/run_doctoc.sh",
            }
            or value.startswith(("docs/", "tests/", "scripts/backend_release/"))
        ):
            reason = "unknown_runtime_asset"
            break
    if any(f.path not in RUNTIME_FILES for f in requested.code.files):
        reason = "unknown_runtime_asset"
    if requested.policy_digest != accepted.policy_digest:
        reason = "unit_policy_review"
    if observed_unit_digest != accepted.unit_digest:
        reason = "installed_unit_drift"

    if reason:
        action = "review"
    elif (
        requested.code.runtime_digest != accepted.code.runtime_digest
        or requested.environment.identity_digest != accepted.environment.identity_digest
    ):
        action, reason = "transaction", "pending_runtime_difference"
    elif force_restart:
        action, reason = "transaction", "explicit_restart"
    else:
        action, reason = "source_sync_only", "accepted_runtime_unchanged"
    return ChangeDecision(
        action,
        source_checkout_sha,
        accepted.code.source_sha,
        requested.code.source_sha,
        reason,
    )


def environment_reusable(
    accepted: EnvironmentEvidence,
    observed: EnvironmentEvidence,
    *,
    inventory_checked: bool,
    pip_check_passed: bool,
) -> bool:
    require(
        type(accepted) is EnvironmentEvidence and type(observed) is EnvironmentEvidence,
        "Invalid environment evidence",
    )
    boolean(inventory_checked)
    boolean(pip_check_passed)
    return (
        inventory_checked
        and pip_check_passed
        and accepted.identity_digest == observed.identity_digest
    )


def retained_environments(
    current: EnvironmentEvidence,
    previous: EnvironmentEvidence | None,
    active: tuple[EnvironmentEvidence, ...],
    candidate: EnvironmentEvidence,
) -> tuple[str, ...]:
    require(type(active) is tuple and len(active) <= 8, "Invalid active references")
    values = (current, candidate, *active)
    if previous is not None:
        values += (previous,)
    require(all(type(e) is EnvironmentEvidence for e in values), "Invalid environment")
    paths = {}
    for value in values:
        require(value.fixtures == current.fixtures, "Fixture roots changed")
        prior = paths.setdefault(value.final_path, value.identity_digest)
        require(
            prior == value.identity_digest, "Conflicting identity at fixed env path"
        )
    require(len(paths) <= 2, "Third distinct environment requires separate review")
    return tuple(sorted(paths))


@dataclass(frozen=True)
class AdoptionPlan:
    source_sha: str
    snapshot_path: str
    unchanged_env_path: str
    source_sync_allowed: bool = False


def plan_adoption(baseline: Release, source_checkout_sha: str) -> AdoptionPlan:
    require(type(baseline) is Release, "Invalid baseline")
    digest(source_checkout_sha, 40)
    require(
        baseline.code.source_sha == source_checkout_sha,
        "Source advanced before adoption",
    )
    require(baseline.environment.origin == "legacy", "Adopt the original environment")
    return AdoptionPlan(
        source_checkout_sha,
        baseline.environment.fixtures.code(source_checkout_sha),
        baseline.environment.final_path,
    )
