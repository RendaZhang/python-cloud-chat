from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from scripts.backend_release.contracts import ContractError
from scripts.backend_release.state import (
    Checks,
    FORWARD_SECONDS,
    RECOVERY_SECONDS,
    TOTAL_SECONDS,
    deadline_decision,
    prepare,
    source_sync_allowed,
    transition,
)
from tests.backend_release_fixtures import changed_runtime, environment, release


class BackendReleaseStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = release(self.root)
        self.new = changed_runtime(release(self.root, 2))
        self.state = prepare(
            self.old, self.new, source_checkout_sha=self.new.code.source_sha
        )
        self.owner = self.state.owner

    def change(self, event, *, state=None, now=100, **kwargs):
        return transition(state or self.state, self.owner, event, now=now, **kwargs)

    def checks(self, release):
        return Checks(release.identity_digest, True, True, True, True)

    def test_preparation_is_pure_and_does_not_start_deadline(self):
        self.assertEqual(self.state.phase, "prepared")
        self.assertIsNone(self.state.started_at)
        self.assertEqual(self.state.serving, self.old)
        self.assertEqual(deadline_decision(self.state, self.owner, 9000), "none")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_activation_binds_one_nonresetting_clock(self):
        active = self.change("activate")
        self.assertEqual(active.started_at, 100)
        self.assertIsNone(active.serving)
        self.assertFalse(source_sync_allowed(active))
        self.assertEqual(self.state.phase, "prepared")
        with self.assertRaises(ContractError):
            self.change("activate", state=active, now=120)
        with self.assertRaises(ContractError):
            self.change("fail", state=active, now=99, failure="start")

    def test_acceptance_commits_new_triple_and_cannot_be_undone_by_guard(self):
        active = self.change("activate")
        accepted = self.change(
            "accept", state=active, now=130, checks=self.checks(self.new)
        )
        self.assertEqual(accepted.accepted, self.new)
        self.assertEqual(accepted.serving, self.new)
        self.assertEqual(accepted.baseline, self.old)
        self.assertEqual(deadline_decision(accepted, self.owner, 1000), "none")
        with self.assertRaises(ContractError):
            self.change("fail", state=accepted, now=500, failure="caller_lost")

    def test_acceptance_rejects_wrong_identity_or_missing_gates(self):
        active = self.change("activate")
        for checks in (
            None,
            self.checks(self.old),
            replace(self.checks(self.new), public_health=False),
            replace(self.checks(self.new), isolation=False),
        ):
            with self.subTest(checks=checks), self.assertRaises(ContractError):
                self.change("accept", state=active, now=110, checks=checks)
        with self.assertRaises(ContractError):
            Checks(self.new.identity_digest, 1, True, True, True)

    def test_failure_and_recovery_preserve_original_failed_outcome(self):
        active = self.change("activate")
        failed = self.change("fail", state=active, now=125, failure="health")
        recovered = self.change(
            "recover", state=failed, now=200, checks=self.checks(self.old)
        )
        self.assertEqual(recovered.phase, "recovered")
        self.assertEqual(recovered.failure, "health")
        self.assertEqual(recovered.accepted, self.old)
        self.assertEqual(recovered.serving, self.old)
        self.assertEqual(recovered.source_checkout_sha, self.new.code.source_sha)
        self.assertEqual(recovered.started_at, 100)
        with self.assertRaises(ContractError):
            self.change(
                "accept", state=recovered, now=201, checks=self.checks(self.new)
            )

    def test_recovery_repeats_all_checks_and_uses_baseline_identity(self):
        failed = self.change(
            "fail", state=self.change("activate"), now=120, failure="start"
        )
        for checks in (
            self.checks(self.new),
            replace(self.checks(self.old), unit=False),
            replace(self.checks(self.old), internal_health=False),
        ):
            with self.subTest(checks=checks), self.assertRaises(ContractError):
                self.change("recover", state=failed, now=130, checks=checks)

    def test_stale_generation_run_attempt_and_request_are_fenced(self):
        for owner in (
            self.old.request,
            replace(self.owner, run_id=124),
            replace(self.owner, attempt=3),
            replace(self.owner, request_id="other"),
        ):
            with self.subTest(owner=owner), self.assertRaises(ContractError):
                transition(self.state, owner, "activate", now=100)
        next_release = release(self.root, 3)
        newer = prepare(
            self.old, next_release, source_checkout_sha=next_release.code.source_sha
        )
        with self.assertRaises(ContractError):
            transition(newer, self.owner, "fail", now=100, failure="timeout")

    def test_same_or_older_generation_and_reused_request_refused(self):
        for request in (
            self.old.request,
            replace(self.new.request, generation=1),
            replace(self.new.request, request_id=self.old.request.request_id),
        ):
            with self.subTest(request=request), self.assertRaises(ContractError):
                prepare(
                    self.old,
                    replace(self.new, request=request),
                    source_checkout_sha=self.new.code.source_sha,
                )

    def test_shared_deadline_arithmetic_and_boundaries(self):
        self.assertEqual(
            (FORWARD_SECONDS, RECOVERY_SECONDS, TOTAL_SECONDS), (270, 210, 480)
        )
        active = self.change("activate")
        self.assertEqual(deadline_decision(active, self.owner, 369), "continue")
        self.assertEqual(deadline_decision(active, self.owner, 370), "recover")
        self.assertEqual(deadline_decision(active, self.owner, 580), "fail_closed")
        with self.assertRaises(ContractError):
            self.change("accept", state=active, now=370, checks=self.checks(self.new))
        failed = self.change("fail", state=active, now=370, failure="timeout")
        self.assertEqual(
            self.change(
                "recover", state=failed, now=579, checks=self.checks(self.old)
            ).phase,
            "recovered",
        )
        with self.assertRaises(ContractError):
            self.change("recover", state=failed, now=580, checks=self.checks(self.old))

    def test_terminal_record_cannot_declare_an_expired_success(self):
        active = self.change("activate")
        with self.assertRaises(ContractError):
            replace(active, phase="accepted", last_at=370)
        with self.assertRaises(ContractError):
            replace(active, phase="recovered", failure="health", last_at=580)

    def test_failure_before_activation_does_not_claim_an_outage(self):
        failed = self.change("fail", failure="start")
        self.assertIsNone(failed.started_at)
        self.assertEqual(failed.serving, self.old)
        self.assertEqual(deadline_decision(failed, self.owner, 500), "none")

    def test_uncertain_and_degraded_never_claim_known_running_release(self):
        active = self.change("activate")
        uncertain = self.change("uncertain", state=active, now=110)
        self.assertIsNone(uncertain.serving)
        self.assertEqual(deadline_decision(uncertain, self.owner, 110), "recover")
        degraded = self.change("degrade", state=uncertain, now=580)
        self.assertEqual(degraded.failure, "uncertain")
        self.assertIsNone(degraded.serving)
        self.assertEqual(deadline_decision(degraded, self.owner, 580), "fail_closed")

    def test_failure_reason_and_times_are_controlled(self):
        for value in ("visitor text", {}, None):
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.change("fail", failure=value)
        for value in (True, 1.0, -1):
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.change("activate", now=value)

    def test_adoption_source_sync_requires_committed_baseline(self):
        candidate = replace(release(self.root, 2), code=self.old.code)
        adoption = prepare(
            self.old,
            candidate,
            source_checkout_sha=self.old.code.source_sha,
            kind="adoption",
        )
        self.assertFalse(source_sync_allowed(adoption))
        active = self.change("activate", state=adoption)
        self.assertFalse(source_sync_allowed(active))
        committed = self.change(
            "accept", state=active, now=120, checks=self.checks(candidate)
        )
        self.assertTrue(source_sync_allowed(committed))
        failed = self.change("fail", state=active, now=110, failure="health")
        recovered = self.change(
            "recover", state=failed, now=120, checks=self.checks(self.old)
        )
        self.assertFalse(source_sync_allowed(recovered))

    def test_adoption_rejects_code_environment_policy_or_checkout_changes(self):
        baseline_candidate = replace(release(self.root, 2), code=self.old.code)
        variants = (
            changed_runtime(baseline_candidate),
            replace(baseline_candidate, environment=environment(self.root, "copied")),
            replace(baseline_candidate, policy_digest="0" * 64),
        )
        for candidate in variants:
            with self.subTest(identity=candidate.identity_digest), self.assertRaises(
                ContractError
            ):
                prepare(
                    self.old,
                    candidate,
                    source_checkout_sha=self.old.code.source_sha,
                    kind="adoption",
                )
        with self.assertRaises(ContractError):
            prepare(
                self.old,
                baseline_candidate,
                source_checkout_sha="3" * 40,
                kind="adoption",
            )
