from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.backend_release.contracts import ContractError, PackageEvidence
from scripts.backend_release.decisions import (
    PHYSICAL_RESERVE_MIB,
    PROPOSED_DISK_MIB,
    PROPOSED_PREPARATION_MIB,
    classify,
    environment_reusable,
    plan_adoption,
    retained_environments,
)
from scripts.backend_release.unit import CANONICAL_POLICY_DIGEST, render_unit
from tests.backend_release_fixtures import changed_runtime, environment, release


class BackendReleaseDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.accepted = release(self.root)
        self.target = release(self.root, 2)

    def classify(self, requested=None, **options):
        defaults = dict(
            source_checkout_sha="3" * 40,
            changed_paths=("docs/TESTING.md",),
            observed_unit_digest=self.accepted.unit_digest,
        )
        defaults.update(options)
        return classify(self.accepted, requested or self.target, **defaults)

    def test_docs_only_preserves_serving_identity(self):
        result = self.classify()
        self.assertEqual(result.action, "source_sync_only")
        self.assertEqual(result.serving_source_sha, "1" * 40)
        self.assertEqual(result.source_checkout_sha, "3" * 40)
        self.assertEqual(result.requested_source_sha, "2" * 40)

    def test_force_restart_requires_transaction(self):
        self.assertEqual(self.classify(force_restart=True).reason, "explicit_restart")
        with self.assertRaises(ContractError):
            self.classify(force_restart=1)

    def test_docs_commit_after_failed_code_update_keeps_pending_difference(self):
        result = self.classify(
            changed_runtime(self.target),
            source_checkout_sha=self.target.code.source_sha,
        )
        self.assertEqual(result.action, "transaction")
        self.assertEqual(result.reason, "pending_runtime_difference")

    def test_dependency_difference_cannot_be_docs_only(self):
        target = replace(
            self.target,
            environment=replace(self.target.environment, requirements_digest="0" * 64),
        )
        self.assertEqual(self.classify(target).action, "transaction")

    def test_unknown_assets_schema_and_runtime_pins_require_review(self):
        for value in (
            "templates/new.html",
            "settings.json",
            "schema.sql",
            ".python-version",
            ".mise.toml",
        ):
            with self.subTest(value=value):
                self.assertEqual(self.classify(changed_paths=(value,)).action, "review")
        extra = replace(self.target.code.files[0], path="resource.json")
        target = replace(
            self.target,
            code=replace(self.target.code, files=self.target.code.files + (extra,)),
        )
        self.assertEqual(self.classify(target).reason, "unknown_runtime_asset")

    def test_unit_policy_and_installed_drift_require_review_even_when_forced(self):
        changed = replace(self.target, policy_digest="0" * 64)
        self.assertEqual(self.classify(changed).reason, "unit_policy_review")
        self.assertEqual(
            self.classify(observed_unit_digest="0" * 64, force_restart=True).reason,
            "installed_unit_drift",
        )

    def test_changed_paths_are_bounded_unique_and_relative(self):
        for paths in (
            ("README.md", "README.md"),
            ("../app.py",),
            ("/app.py",),
            ("x",) * 513,
        ):
            with self.subTest(count=len(paths)), self.assertRaises(ContractError):
                self.classify(changed_paths=paths)

    def test_reuse_requires_inventory_and_pip_evidence(self):
        env = self.accepted.environment
        self.assertTrue(
            environment_reusable(
                env, env, inventory_checked=True, pip_check_passed=True
            )
        )
        for flags in ((False, True), (True, False), (False, False)):
            self.assertFalse(
                environment_reusable(
                    env, env, inventory_checked=flags[0], pip_check_passed=flags[1]
                )
            )
        with self.assertRaises(ContractError):
            environment_reusable(env, env, inventory_checked=1, pip_check_passed=True)

    def test_equal_requirements_alone_never_approve_reuse(self):
        env = self.accepted.environment
        candidates = (
            replace(env, interpreter=replace(env.interpreter, binary_digest="0" * 64)),
            replace(
                env,
                interpreter=replace(
                    env.interpreter, base_path=str(self.root / "other/python")
                ),
            ),
            replace(env, platform=replace(env.platform, architecture="aarch64")),
            replace(env, platform=replace(env.platform, libc="glibc-2.40")),
            replace(
                env, packages=(replace(env.packages[0], inventory_digest="0" * 64),)
            ),
            replace(
                env, packages=env.packages + (PackageEvidence("extra", "1", "0" * 64),)
            ),
            environment(self.root, "new-fixed-path"),
        )
        for candidate in candidates:
            with self.subTest(identity=candidate.identity_digest):
                self.assertEqual(candidate.requirements_digest, env.requirements_digest)
                self.assertFalse(
                    environment_reusable(
                        env, candidate, inventory_checked=True, pip_check_passed=True
                    )
                )

    def test_retention_shares_environment_and_preserves_legacy(self):
        old = self.accepted.environment
        new = environment(self.root, "new")
        paths = retained_environments(old, old, (old,), new)
        self.assertEqual(set(paths), {old.final_path, new.final_path})
        self.assertEqual(retained_environments(old, old, (), old), (old.final_path,))

    def test_third_environment_is_refused_including_active_references(self):
        old, new, third = (
            environment(self.root, key) for key in ("legacy", "new", "third")
        )
        with self.assertRaises(ContractError):
            retained_environments(new, old, (), third)
        with self.assertRaises(ContractError):
            retained_environments(new, new, (old,), third)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_conflicting_identity_at_same_environment_path_is_refused(self):
        old = self.accepted.environment
        changed = replace(old, requirements_digest="0" * 64)
        with self.assertRaises(ContractError):
            retained_environments(old, None, (), changed)

    def test_adoption_precedes_source_sync_and_keeps_original_environment(self):
        plan = plan_adoption(self.accepted, self.accepted.code.source_sha)
        self.assertFalse(plan.source_sync_allowed)
        self.assertEqual(plan.unchanged_env_path, self.accepted.environment.final_path)
        self.assertEqual(
            plan.snapshot_path,
            self.accepted.environment.fixtures.code(self.accepted.code.source_sha),
        )
        with self.assertRaises(ContractError):
            plan_adoption(self.accepted, self.target.code.source_sha)
        with self.assertRaises(ContractError):
            plan_adoption(
                replace(self.accepted, environment=environment(self.root, "new")),
                self.accepted.code.source_sha,
            )

    def test_resource_numbers_are_proposals_not_capacity_observations(self):
        self.assertEqual(PROPOSED_DISK_MIB, 2 * 384 + 64 + 256 + 128 + 64)
        self.assertEqual(PROPOSED_PREPARATION_MIB + PHYSICAL_RESERVE_MIB, 256)
        self.assertEqual(list(self.root.iterdir()), [])


class BackendReleaseUnitRenderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = environment(self.root, "ready-1")
        self.policy = (
            Path(__file__).resolve().parents[1] / "deploy/cloudchat.service"
        ).read_text()

    def render(self, **kwargs):
        return render_unit(
            self.policy, source_sha="1" * 40, environment=self.env, **kwargs
        )

    def test_policy_digest_is_current_and_live_only_substitutes_paths(self):
        self.assertEqual(
            hashlib.sha256(self.policy.encode()).hexdigest(), CANONICAL_POLICY_DIGEST
        )
        result = self.render()
        original = self.policy.splitlines()
        rendered = result.splitlines()
        self.assertEqual(len(original), len(rendered))
        changed = [
            before.split("=", 1)[0]
            for before, after in zip(original, rendered)
            if before != after
        ]
        self.assertEqual(changed, ["WorkingDirectory", "ExecStart"])
        self.assertIn("WorkingDirectory=" + self.env.fixtures.code("1" * 40), result)
        self.assertIn("ExecStart=" + self.env.final_path + "/bin/gunicorn", result)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_candidate_preserves_all_except_reviewed_substitutions(self):
        result = self.render(candidate_id="r1-a1-g2")
        prefixes = (
            "WorkingDirectory=",
            "ExecStart=",
            "Environment=HOME=",
            "StateDirectory=",
            "StateDirectoryMode=",
            "RuntimeDirectory=",
            "Restart=",
            "RuntimeMaxSec=",
        )

        def unchanged(value):
            return [
                line for line in value.splitlines() if not line.startswith(prefixes)
            ]

        self.assertEqual(unchanged(result), unchanged(self.policy))
        self.assertIn("--bind 127.0.0.1:5001", result)
        self.assertIn(
            "--worker-class gevent --workers 2 --worker-connections 50", result
        )
        self.assertIn("--worker-tmp-dir /run/cloudchat-preflight-r1-a1-g2", result)
        self.assertIn("Restart=no\nRuntimeMaxSec=35", result)
        self.assertNotIn("StateDirectory=", result)
        for line in (
            "User=cloudchat",
            "Group=cloudchat",
            "TimeoutStopSec=90",
            "MemoryHigh=250M",
            "MemoryMax=300M",
            "TasksMax=128",
            "CapabilityBoundingSet=",
            "AmbientCapabilities=",
            "NoNewPrivileges=true",
        ):
            self.assertIn(line, result)

    def test_unknown_policy_or_weakened_directive_refused(self):
        for policy in (
            self.policy + "\nExecStart=/bin/sh\n",
            self.policy.replace("ProtectSystem=strict", "ProtectSystem=false"),
            self.policy.replace("--workers 2", "--workers 3"),
        ):
            with self.subTest(length=len(policy)), self.assertRaises(ContractError):
                render_unit(policy, source_sha="1" * 40, environment=self.env)

    def test_candidate_name_cannot_inject_unit_or_paths(self):
        for value in ("../live", "a\nUser=root", "%h", "", "x" * 65):
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.render(candidate_id=value)

    def test_legacy_environment_entrypoint_remains_at_original_absolute_path(self):
        env = environment(self.root)
        result = render_unit(self.policy, source_sha="1" * 40, environment=env)
        self.assertIn("ExecStart=" + env.fixtures.legacy_env + "/bin/gunicorn", result)
        self.assertFalse((self.root / "legacy").exists())
