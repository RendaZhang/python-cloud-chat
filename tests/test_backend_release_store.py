from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts.backend_release.contracts import ContractError, MAX_RECORD_BYTES
from scripts.backend_release.records import parse_record
from scripts.backend_release.state import Checks, prepare
from scripts.backend_release.store import (
    ClockMismatch,
    DurabilityUncertain,
    FixtureStore,
    LOCK,
    PENDING,
    SLOTS,
    STATE,
)
from tests.backend_release_fixtures import release

CLOCK = "a" * 64


class StoreFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.old = release(self.root)
        self.new = release(self.root, 2)
        self.tx = prepare(
            self.old, self.new, source_checkout_sha=self.new.code.source_sha
        )
        self.fixtures = self.old.environment.fixtures
        self.store = FixtureStore(self.fixtures, clock_context=CLOCK)
        self.record = self.store.initialize(self.tx, owner=self.tx.owner)

    def activate(self):
        self.record = self.store.advance(
            self.record, self.tx.owner, "activate", now=100
        )
        return self.record

    def accept(self):
        self.activate()
        self.record = self.store.advance(
            self.record,
            self.tx.owner,
            "accept",
            now=110,
            checks=Checks(self.new.identity_digest, True, True, True, True),
        )
        return self.record

    def reopen(self, context=CLOCK):
        return FixtureStore(self.fixtures, clock_context=context)

    def write_raw(self, data):
        (self.root / STATE).write_bytes(data)


class DurableRecordTests(StoreFixture):
    def test_round_trip_binds_source_serving_owner_and_predecessor(self):
        self.assertEqual(
            parse_record(self.record.encode().decode(), self.fixtures), self.record
        )
        active = self.activate()
        self.assertEqual(active.revision, 2)
        self.assertIsNone(active.transaction.serving)
        self.assertEqual(
            active.transaction.source_checkout_sha, self.new.code.source_sha
        )
        self.assertEqual(active.transaction.accepted, self.old)
        self.assertEqual(self.reopen().read(), active)

    def test_record_inventory_order_is_canonical(self):
        tx = self.record.transaction
        reordered = replace(
            tx,
            baseline=replace(
                tx.baseline,
                code=replace(
                    tx.baseline.code, files=tuple(reversed(tx.baseline.code.files))
                ),
            ),
        )
        self.assertEqual(
            replace(self.record, transaction=reordered).encode(), self.record.encode()
        )

    def test_schema_keys_checksum_and_identity_mismatches_fail_closed(self):
        original = json.loads(self.record.encode())
        for key, value in (
            ("schema", 2),
            ("schema", True),
            ("extra", "unknown"),
            ("revision", False),
            ("record_digest", "f" * 64),
            ("accepted_digest", self.new.identity_digest),
            ("serving_digest", None),
            ("clock_context", "unknown"),
            ("lock_inode", -1),
            ("lock_device", True),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ContractError):
                parse_record(json.dumps(dict(original, **{key: value})), self.fixtures)
        for key in original:
            data = dict(original)
            del data[key]
            with self.subTest(missing=key), self.assertRaises(ContractError):
                parse_record(json.dumps(data), self.fixtures)

    def test_nested_owner_transaction_and_release_rejections(self):
        for target, key, value in (
            ("owner", "generation", 55),
            ("transaction", "phase", "accepted"),
            ("transaction", "failure", "raw application output"),
            ("transaction", "new", "field"),
        ):
            data = json.loads(self.record.encode())
            data[target][key] = value
            with self.subTest(target=target, key=key), self.assertRaises(ContractError):
                parse_record(json.dumps(data), self.fixtures)
        data = json.loads(self.record.encode())
        data["transaction"]["baseline"]["environment"]["packages"][0]["token"] = "never"
        with self.assertRaises(ContractError):
            parse_record(json.dumps(data), self.fixtures)

    def test_corrupt_oversized_duplicate_and_nonfinite_records_rejected(self):
        for raw in (
            "{",
            "null",
            '{"schema":1,"schema":1}',
            '{"x":NaN}',
            "x" * (MAX_RECORD_BYTES + 1),
        ):
            with self.subTest(length=len(raw)), self.assertRaises(ContractError):
                parse_record(raw, self.fixtures)
        for revision, previous in ((1, "a" * 64), (2, None)):
            with self.assertRaises(ContractError):
                replace(self.record, revision=revision, previous_digest=previous)

    def test_combined_record_cannot_silently_exceed_existing_bound(self):
        extra = tuple(
            replace(self.old.code.files[0], path=f"asset-{i}.py") for i in range(300)
        )
        big = replace(
            self.old, code=replace(self.old.code, files=self.old.code.files + extra)
        )
        tx = replace(
            self.tx, baseline=big, requested=replace(big, request=self.new.request)
        )
        with self.assertRaises(ContractError):
            replace(self.record, transaction=tx).encode()


class FixtureStoreTests(StoreFixture):
    def test_constructor_and_status_issue_only_read_opens(self):
        original = os.open

        def read_only(name, flags, *args, **kwargs):
            self.assertFalse(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            )
            return original(name, flags, *args, **kwargs)

        with patch("scripts.backend_release.store.os.open", side_effect=read_only):
            with patch(
                "scripts.backend_release.store.os.write",
                side_effect=AssertionError("write"),
            ):
                self.assertEqual(self.reopen().read(), self.record)

    def test_constructor_and_read_never_initialize_missing_files(self):
        empty = self.root / "empty"
        empty.mkdir(mode=0o700)
        env = release(empty).environment
        store = FixtureStore(env.fixtures, clock_context=CLOCK)
        with self.assertRaises(FileNotFoundError):
            store.read()
        self.assertEqual(list(empty.iterdir()), [])
        missing = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            FixtureStore(release(missing).environment.fixtures, clock_context=CLOCK)
        self.assertFalse(missing.exists())

    def test_explicit_initialization_is_private_and_cannot_overwrite(self):
        self.assertEqual({p.name for p in self.root.iterdir()}, {LOCK, STATE, *SLOTS})
        for name in (LOCK, STATE, *SLOTS):
            self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o600)
        before = (self.root / STATE).read_bytes()
        with self.assertRaises(ContractError):
            self.store.initialize(self.tx, owner=self.tx.owner)
        self.assertEqual((self.root / STATE).read_bytes(), before)
        self.assertFalse((self.root / PENDING).exists())

    def test_status_does_not_write_or_create_temporary_files(self):
        before = {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()
        }
        self.assertEqual(self.reopen().read(), self.record)
        self.assertEqual(self.store.deadline(owner=self.tx.owner, now=1), "none")
        self.assertEqual(
            before,
            {
                p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.iterdir()
            },
        )

    def test_missing_lock_is_not_recreated_by_read_or_write(self):
        (self.root / LOCK).unlink()
        for operation in (self.store.read, lambda: self.activate()):
            with self.assertRaises(FileNotFoundError):
                operation()
        self.assertFalse((self.root / LOCK).exists())

    def test_stale_snapshot_and_stale_owner_are_rejected_under_lock(self):
        prior = self.record
        active = self.activate()
        with self.assertRaises(ContractError):
            self.store.advance(prior, self.tx.owner, "fail", now=101, failure="health")
        with self.assertRaises(ContractError):
            self.store.advance(
                active, self.old.request, "fail", now=101, failure="health"
            )
        self.assertEqual(self.store.read(), active)

    def test_terminal_acceptance_cannot_be_rewritten(self):
        accepted = self.accept()
        for event in ("fail", "recover", "uncertain", "activate"):
            with self.subTest(event=event), self.assertRaises(ContractError):
                self.store.advance(
                    accepted, self.tx.owner, event, now=111, failure="health"
                )
        self.assertTrue(self.store.read().successful)

    def test_next_generation_fences_old_callback_even_with_fresh_snapshot(self):
        accepted = self.accept()
        next_release = release(self.root, 3)
        pending = self.store.begin(
            accepted,
            next_release.request,
            next_release,
            source_checkout_sha=next_release.code.source_sha,
        )
        self.assertEqual(pending.transaction.baseline, accepted.transaction.accepted)
        self.assertEqual(pending.clock_context, accepted.clock_context)
        with self.assertRaises(ContractError):
            self.store.advance(pending, self.tx.owner, "activate", now=200)
        with self.assertRaises(ContractError):
            self.store.begin(
                pending,
                self.tx.owner,
                self.new,
                source_checkout_sha=self.new.code.source_sha,
            )

    def test_recovered_outcome_stays_failed_to_caller(self):
        active = self.activate()
        failed = self.store.advance(
            active, self.tx.owner, "fail", now=110, failure="health"
        )
        recovered = self.store.advance(
            failed,
            self.tx.owner,
            "recover",
            now=120,
            checks=Checks(self.old.identity_digest, True, True, True, True),
        )
        observed = self.reopen().read()
        self.assertEqual(observed, recovered)
        self.assertFalse(observed.successful)
        self.assertEqual(observed.transaction.failure, "health")
        self.assertEqual(observed.transaction.accepted, self.old)

    def test_clock_survives_reopen_and_exhaustion_cannot_reset(self):
        active = self.activate()
        reopened = self.reopen()
        self.assertEqual(reopened.read().transaction.started_at, 100)
        self.assertEqual(reopened.deadline(owner=self.tx.owner, now=580), "fail_closed")
        for event in ("activate", "accept"):
            with self.assertRaises(ContractError):
                reopened.advance(
                    active,
                    self.tx.owner,
                    event,
                    now=580,
                    checks=Checks(self.new.identity_digest, True, True, True, True),
                )
        failed = reopened.advance(
            active, self.tx.owner, "fail", now=580, failure="timeout"
        )
        with self.assertRaises(ContractError):
            reopened.advance(
                failed,
                self.tx.owner,
                "recover",
                now=581,
                checks=Checks(self.old.identity_digest, True, True, True, True),
            )

    def test_changed_or_unknown_clock_cannot_claim_recovery_or_reset(self):
        active = self.activate()
        before = (self.root / STATE).read_bytes()
        other = self.reopen("b" * 64)
        for call in (
            other.read,
            lambda: other.advance(
                active, self.tx.owner, "fail", now=1, failure="timeout"
            ),
        ):
            with self.assertRaises(ClockMismatch):
                call()
        with self.assertRaises(ContractError):
            self.reopen("")
        self.assertEqual((self.root / STATE).read_bytes(), before)

    def test_invalid_truncated_utf8_and_oversized_state_fail_without_repair(self):
        for raw in (b"{", b"\xff", b"x" * (MAX_RECORD_BYTES + 1)):
            self.write_raw(raw)
            with self.subTest(length=len(raw)), self.assertRaises(
                (ContractError, UnicodeError)
            ):
                self.store.read()
            self.assertEqual((self.root / STATE).read_bytes(), raw)
            self.assertFalse((self.root / PENDING).exists())

    def test_short_writes_are_completed(self):
        original = os.write
        with patch(
            "scripts.backend_release.store.os.write",
            side_effect=lambda fd, data: original(fd, data[:97]),
        ):
            active = self.activate()
        self.assertEqual(self.store.read(), active)

    def test_write_error_and_zero_write_leave_old_authority(self):
        before = self.record
        for result in (OSError("injected write failure"), 0):
            kwargs = (
                {"side_effect": result}
                if isinstance(result, Exception)
                else {"return_value": result}
            )
            with patch("scripts.backend_release.store.os.write", **kwargs):
                with self.assertRaises((OSError, ContractError)):
                    self.activate()
            self.assertEqual(self.store.read(), before)
            self.assertFalse((self.root / PENDING).exists())

    def test_partial_write_exception_leaves_reusable_owned_slot(self):
        original = os.write
        calls = 0

        def partial(fd, raw):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise OSError("injected partial write")
            return original(fd, raw[:17])

        with patch("scripts.backend_release.store.os.write", side_effect=partial):
            with self.assertRaises(OSError):
                self.activate()
        self.assertEqual(self.reopen().read(), self.record)
        self.activate()
        self.assertEqual(self.reopen().read(), self.record)

    def test_file_fsync_or_replace_failure_preserves_old_state(self):
        for operation in ("fsync", "replace"):
            with patch(
                "scripts.backend_release.store.os." + operation,
                side_effect=OSError("injected failure"),
            ):
                with self.assertRaises((OSError, DurabilityUncertain)):
                    self.activate()
            self.assertEqual(self.store.read(), self.record)
            self.assertFalse((self.root / PENDING).exists())

    def test_directory_fsync_failure_reports_uncertain_not_old_success(self):
        active = self.activate()
        original = os.fsync

        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected directory fsync failure")
            original(fd)

        with patch(
            "scripts.backend_release.store.os.fsync", side_effect=fail_directory
        ):
            with self.assertRaises(DurabilityUncertain):
                self.store.advance(
                    active,
                    self.tx.owner,
                    "accept",
                    now=110,
                    checks=Checks(self.new.identity_digest, True, True, True, True),
                )
        observed = self.reopen().read()
        self.assertTrue(observed.successful)
        with self.assertRaises(ContractError):
            self.store.advance(
                observed, self.tx.owner, "fail", now=111, failure="health"
            )
        with self.assertRaises(ContractError):
            self.reopen().advance(
                observed, self.tx.owner, "fail", now=111, failure="health"
            )

    def test_exception_after_replace_effect_is_explicitly_uncertain(self):
        original = os.replace

        def replace_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("injected lost replacement result")

        with patch(
            "scripts.backend_release.store.os.replace", side_effect=replace_then_fail
        ):
            with self.assertRaises(DurabilityUncertain):
                self.activate()
        observed = self.reopen().read()
        self.assertEqual(observed.transaction.phase, "activating")
        self.assertEqual(observed.revision, 2)

    def test_directory_swap_during_read_is_refused_without_repair(self):
        nested = self.root / "nested"
        nested.mkdir(mode=0o700)
        old, new = release(nested), release(nested, 2)
        tx = prepare(old, new, source_checkout_sha=new.code.source_sha)
        store = FixtureStore(old.environment.fixtures, clock_context=CLOCK)
        record = store.initialize(tx, owner=tx.owner)

        def swap(stage):
            if stage == "read_opened":
                nested.rename(self.root / "moved")
                nested.mkdir(mode=0o700)

        with patch.object(store, "_checkpoint", side_effect=swap):
            with self.assertRaises(ContractError):
                store.read()
        self.assertEqual(list(nested.iterdir()), [])
        self.assertEqual((self.root / "moved" / STATE).read_bytes(), record.encode())

    def test_unknown_pending_file_is_preserved_and_refused(self):
        orphan = self.root / PENDING
        orphan.write_text("unknown inode, not proven owned")
        orphan.chmod(0o600)
        before = (self.root / STATE).read_bytes()
        with self.assertRaises(ContractError):
            self.activate()
        self.assertEqual(orphan.read_text(), "unknown inode, not proven owned")
        self.assertEqual((self.root / STATE).read_bytes(), before)

    def test_unsafe_modes_and_owner_rejected(self):
        for name in (STATE, LOCK):
            item = self.root / name
            item.chmod(0o644)
            with self.assertRaises(ContractError):
                self.store.read()
            item.chmod(0o600)
        self.root.chmod(0o755)
        with self.assertRaises(ContractError):
            self.reopen()
        self.root.chmod(0o700)
        with patch(
            "scripts.backend_release.store.os.geteuid", return_value=os.geteuid() + 1
        ):
            with self.assertRaises(ContractError):
                self.reopen()

    def test_symlink_special_file_and_hardlink_are_not_followed(self):
        original = (self.root / STATE).read_bytes()
        target = self.root / "target"
        target.write_bytes(original)
        target.chmod(0o600)
        for kind in ("symlink", "fifo", "hardlink"):
            item = self.root / STATE
            item.unlink()
            if kind == "symlink":
                item.symlink_to(target)
            elif kind == "fifo":
                os.mkfifo(item, 0o600)
            else:
                os.link(target, item)
            with self.subTest(kind=kind), self.assertRaises((OSError, ContractError)):
                self.store.read()
            self.assertEqual(target.read_bytes(), original)

    def test_replaced_lock_inode_cannot_split_ownership(self):
        original = self.root / LOCK
        original.rename(self.root / "old-lock")
        original.touch(mode=0o600)
        for operation in (self.store.read, lambda: self.activate()):
            with self.assertRaises(ContractError):
                operation()
        self.assertTrue((self.root / "old-lock").exists())

    def test_root_replacement_is_rejected_by_existing_handle(self):
        moved = self.root / "inner"
        moved.mkdir(mode=0o700)
        other_store = FixtureStore(
            release(moved).environment.fixtures, clock_context=CLOCK
        )
        moved.rename(self.root / "old-inner")
        moved.mkdir(mode=0o700)
        with self.assertRaises(ContractError):
            other_store.read()
        self.assertEqual(list(moved.iterdir()), [])

    def test_parent_symlink_swap_during_write_never_redirects_write(self):
        parent = self.root / "parent"
        parent.mkdir(mode=0o700)
        child = parent / "fixture"
        child.mkdir(mode=0o700)
        target = self.root / "elsewhere"
        target.mkdir(mode=0o700)
        tx = prepare(release(child), release(child, 2), source_checkout_sha="2" * 40)
        store = FixtureStore(tx.baseline.environment.fixtures, clock_context=CLOCK)
        record = store.initialize(tx, owner=tx.owner)

        def swap(stage):
            if stage == "file_synced":
                parent.rename(self.root / "moved-parent")
                parent.symlink_to(target, target_is_directory=True)

        with patch.object(store, "_checkpoint", side_effect=swap):
            with self.assertRaises(ContractError):
                store.advance(record, tx.owner, "activate", now=100)
        self.assertEqual(list(target.iterdir()), [])
        old = self.root / "moved-parent/fixture"
        self.assertEqual((old / STATE).read_bytes(), record.encode())
        self.assertFalse((old / PENDING).exists())
        with self.assertRaises(OSError):
            FixtureStore(tx.baseline.environment.fixtures, clock_context=CLOCK)

    def test_replaced_temporary_name_is_not_unlinked_by_cleanup(self):
        def swap(stage):
            if stage == "linked":
                (self.root / PENDING).rename(self.root / "detached-pending")
                (self.root / PENDING).write_text("not this invocation's inode")
                (self.root / PENDING).chmod(0o600)

        with patch.object(self.store, "_checkpoint", side_effect=swap):
            with self.assertRaises(ContractError):
                self.activate()
        self.assertEqual(
            (self.root / PENDING).read_text(), "not this invocation's inode"
        )
        self.assertEqual((self.root / STATE).read_bytes(), self.record.encode())

    def test_unexpected_reserved_slot_or_extra_hardlink_is_refused(self):
        slot = self.root / SLOTS[1]
        os.link(slot, self.root / "unknown-alias")
        with self.assertRaises(ContractError):
            self.store.read()
        (self.root / "unknown-alias").unlink()
        slot.rename(self.root / "old-slot")
        slot.touch(mode=0o600)
        with self.assertRaises(ContractError):
            self.store.read()

    def test_aliases_use_two_bounded_allocations_and_never_choose_highest_revision(
        self,
    ):
        self.activate()
        inactive = self.root / SLOTS[0]
        inactive.write_bytes(replace(self.record, revision=99).encode())
        self.assertEqual(self.store.read(), self.record)
        (self.root / STATE).unlink()
        with self.assertRaises(FileNotFoundError):
            self.store.read()
        self.assertEqual(len({(self.root / name).stat().st_ino for name in SLOTS}), 2)
