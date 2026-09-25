"""Real owned subprocess faults, executed on both macOS and Linux without skips."""

import multiprocessing
import os
import signal
import sys
import time

from scripts.backend_release.contracts import ContractError
from scripts.backend_release.state import Checks, prepare
from scripts.backend_release.store import FixtureStore, LockBusy, LOCK, PENDING, STATE
from tests.backend_release_fixtures import release
from tests.test_backend_release_store import CLOCK, StoreFixture


def process_worker(connection, fixtures, expected, event, stage=None):
    class PausingStore(FixtureStore):
        def _checkpoint(self, observed):
            if observed == stage:
                connection.send(("paused", observed))
                if connection.recv() != "continue":
                    raise AssertionError("Invalid test barrier")

    try:
        store = PausingStore(fixtures, clock_context=CLOCK)
        connection.send(("ready", os.getpid()))
        if connection.recv() != "go":
            raise AssertionError("Invalid start barrier")
        if event == "read":
            record = store.read()
        elif event == "bootstrap":
            record = store.initialize(expected, owner=expected.owner)
        else:
            tx = expected.transaction
            record = store.advance(
                expected,
                tx.owner,
                event,
                now=110,
                checks=Checks(tx.requested.identity_digest, True, True, True, True),
                failure="health" if event == "fail" else None,
                wait_ms=1000,
            )
        connection.send(("result", record.transaction.phase, record.revision))
    except Exception as error:
        connection.send(("error", type(error).__name__))
    finally:
        connection.close()


class FixtureProcessTests(StoreFixture):
    @classmethod
    def setUpClass(cls):
        cls.executed = 0
        cls.reaped = 0

    @classmethod
    def tearDownClass(cls):
        if multiprocessing.active_children():
            raise AssertionError("Unexpected surviving test children")
        print(
            f"Backend durable process fixtures: platform={sys.platform}; "
            f"cases={cls.executed}; children_reaped={cls.reaped}; skipped=0",
            flush=True,
        )

    def setUp(self):
        super().setUp()
        type(self).executed += 1

    def receive(self, connection):
        self.assertTrue(connection.poll(5), "Child barrier/result timed out")
        return connection.recv()

    def launch(self, event, *, stage=None, expected=None, fixtures=None):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=process_worker,
            args=(
                child,
                fixtures or self.fixtures,
                expected or self.record,
                event,
                stage,
            ),
        )
        process.start()
        child.close()

        def cleanup():
            try:
                if process.is_alive():
                    process.kill()
                process.join(5)
                self.assertFalse(process.is_alive(), "Owned child was not reaped")
                type(self).reaped += 1
            finally:
                parent.close()
                process.close()

        self.addCleanup(cleanup)
        self.assertEqual(self.receive(parent), ("ready", process.pid))
        return process, parent

    def pause(self, event, stage, **kwargs):
        process, connection = self.launch(event, stage=stage, **kwargs)
        connection.send("go")
        self.assertEqual(self.receive(connection), ("paused", stage))
        return process, connection

    def kill(self, child):
        child.kill()
        child.join(5)
        self.assertEqual(child.exitcode, -signal.SIGKILL)

    def recover_and_continue(self, active):
        reopened = self.reopen()
        failed = reopened.advance(
            active, self.tx.owner, "fail", now=120, failure="caller_lost"
        )
        recovered = reopened.advance(
            failed,
            self.tx.owner,
            "recover",
            now=130,
            checks=Checks(self.old.identity_digest, True, True, True, True),
        )
        self.assertFalse(recovered.successful)
        self.assertEqual(recovered.transaction.failure, "caller_lost")
        self.assertEqual(recovered.transaction.started_at, 100)
        self.continue_after(recovered)

    def continue_after(self, terminal):
        next_release = release(self.root, 3)
        store = self.reopen()
        pending = store.begin(
            terminal,
            next_release.request,
            next_release,
            source_checkout_sha=next_release.code.source_sha,
        )
        active = store.advance(pending, next_release.request, "activate", now=200)
        self.assertEqual(store.read(), active)
        self.assertEqual(active.clock_context, CLOCK)
        with self.assertRaises(ContractError):
            store.advance(active, self.tx.owner, "fail", now=201, failure="caller_lost")
        self.assertFalse((self.root / PENDING).exists())

    def interrupt(self, stage, *, committed=False):
        active = self.activate()
        child, _ = self.pause("accept", stage, expected=active)
        with self.assertRaises(LockBusy):
            self.store.read(wait_ms=0)
        self.kill(child)
        observed = self.reopen().read()
        if committed:
            self.assertTrue(observed.successful)
            self.assertEqual(observed.revision, 3)
            with self.assertRaises(ContractError):
                self.store.advance(
                    observed, self.tx.owner, "fail", now=120, failure="caller_lost"
                )
            self.continue_after(observed)
        else:
            self.assertEqual(observed, active)
            self.recover_and_continue(active)

    def test_kill_at_inactive_slot_truncate_then_recover_and_write(self):
        self.interrupt("slot_truncated")

    def test_kill_at_partial_write_then_recover_and_write(self):
        self.interrupt("partial_written")

    def test_kill_at_complete_write_before_fsync_then_recover_and_write(self):
        self.interrupt("written")

    def test_kill_after_file_fsync_then_recover_and_write(self):
        self.interrupt("file_synced")

    def test_kill_after_alias_creation_then_recover_owned_alias_and_write(self):
        self.interrupt("linked")

    def test_kill_after_replacement_then_next_transaction_not_power_loss_proof(self):
        self.interrupt("replaced", committed=True)

    def test_kill_after_directory_fsync_then_next_transaction(self):
        self.interrupt("directory_synced", committed=True)

    def interrupt_cleanup(self, stage):
        active = self.activate()
        first, _ = self.pause("accept", "linked", expected=active)
        self.kill(first)
        self.assertTrue((self.root / PENDING).exists())
        second, _ = self.pause("fail", stage, expected=active)
        self.kill(second)
        self.assertEqual(self.reopen().read(), active)
        self.recover_and_continue(active)

    def test_kill_during_owned_alias_cleanup_then_recover_and_write(self):
        self.interrupt_cleanup("pending_removed")

    def test_kill_after_owned_alias_cleanup_fsync_then_recover_and_write(self):
        self.interrupt_cleanup("pending_cleanup_synced")

    def test_competing_writers_only_one_can_commit_same_expected_record(self):
        first, a = self.launch("activate")
        second, b = self.launch("activate")
        a.send("go")
        b.send("go")
        self.assertCountEqual(
            [self.receive(a), self.receive(b)],
            [("result", "activating", 2), ("error", "ContractError")],
        )
        for child in (first, second):
            child.join(5)
            self.assertEqual(child.exitcode, 0)
        self.assertEqual(self.store.read().revision, 2)

    def test_stale_process_failure_after_acceptance_cannot_overwrite_commit(self):
        active = self.activate()
        child, connection = self.launch("fail", expected=active)
        accepted = self.store.advance(
            active,
            self.tx.owner,
            "accept",
            now=110,
            checks=Checks(self.new.identity_digest, True, True, True, True),
        )
        connection.send("go")
        self.assertEqual(self.receive(connection), ("error", "ContractError"))
        child.join(5)
        self.assertEqual(self.reopen().read(), accepted)

    def test_readers_observe_old_then_new_or_bounded_busy_never_partial_json(self):
        active = self.activate()
        self.assertEqual(self.store.read(), active)
        child, connection = self.pause("accept", "partial_written", expected=active)
        with self.assertRaises(LockBusy):
            self.store.read(wait_ms=0)
        connection.send("continue")
        self.assertEqual(self.receive(connection), ("result", "accepted", 3))
        child.join(5)
        self.assertTrue(self.store.read().successful)

    def test_shared_reader_blocks_slot_reuse_until_read_complete(self):
        active = self.activate()
        child, connection = self.pause("read", "read_opened", expected=active)
        with self.assertRaises(LockBusy):
            self.store.advance(
                active,
                self.tx.owner,
                "accept",
                now=110,
                checks=Checks(self.new.identity_digest, True, True, True, True),
                wait_ms=0,
            )
        connection.send("continue")
        self.assertEqual(self.receive(connection), ("result", "activating", 2))
        child.join(5)
        accepted = self.store.advance(
            active,
            self.tx.owner,
            "accept",
            now=110,
            checks=Checks(self.new.identity_digest, True, True, True, True),
        )
        self.continue_after(accepted)

    def test_killed_lock_holder_releases_kernel_lock_without_inode_replacement(self):
        before = (self.root / LOCK).stat().st_ino
        child, _ = self.pause("activate", "locked")
        self.kill(child)
        active = self.activate()
        self.assertEqual(self.store.read(), active)
        self.assertEqual((self.root / LOCK).stat().st_ino, before)

    def test_stopped_owner_causes_bounded_refusal_not_takeover(self):
        before = (self.root / LOCK).stat().st_ino
        child, connection = self.pause("activate", "locked")
        os.kill(child.pid, signal.SIGSTOP)
        limit = time.monotonic() + 5
        while True:
            pid, status = os.waitpid(child.pid, os.WUNTRACED | os.WNOHANG)
            if pid:
                self.assertTrue(os.WIFSTOPPED(status))
                break
            self.assertLess(time.monotonic(), limit, "Child did not stop")
            time.sleep(0.005)
        start = time.monotonic()
        with self.assertRaises(LockBusy):
            self.store.advance(
                self.record, self.tx.owner, "activate", now=100, wait_ms=50
            )
        self.assertLess(time.monotonic() - start, 2)
        with self.assertRaises(LockBusy):
            self.store.read(wait_ms=0)
        self.assertEqual((self.root / LOCK).stat().st_ino, before)
        self.assertTrue(child.is_alive())
        os.kill(child.pid, signal.SIGCONT)
        connection.send("continue")
        self.assertEqual(self.receive(connection), ("result", "activating", 2))
        child.join(5)

    def test_active_lock_path_replacement_is_detected_without_stealing(self):
        child, connection = self.pause("activate", "locked")
        lock = self.root / LOCK
        lock.rename(self.root / "old-active-lock")
        lock.touch(mode=0o600)
        with self.assertRaises(ContractError):
            self.store.advance(self.record, self.tx.owner, "activate", now=100)
        connection.send("continue")
        self.assertEqual(self.receive(connection), ("error", "ContractError"))
        child.join(5)
        self.assertFalse((self.root / PENDING).exists())
        self.assertEqual(
            (self.root / "old-active-lock").stat().st_ino, self.record.lock_inode
        )

    def bootstrap_interruption(self, stage, *, committed=False):
        root = self.root / "empty-bootstrap"
        root.mkdir(mode=0o700)
        old, new = release(root), release(root, 2)
        tx = prepare(old, new, source_checkout_sha=new.code.source_sha)
        child, _ = self.pause(
            "bootstrap", stage, expected=tx, fixtures=old.environment.fixtures
        )
        self.kill(child)
        reopened = FixtureStore(old.environment.fixtures, clock_context=CLOCK)
        if committed:
            initial = reopened.read()
            active = reopened.advance(initial, tx.owner, "activate", now=100)
            self.assertEqual(reopened.read(), active)
        else:
            self.assertFalse((root / STATE).exists())
            with self.assertRaises(FileNotFoundError):
                reopened.read()
            before = {p.name: p.stat().st_ino for p in root.iterdir()}
            with self.assertRaises(ContractError):
                reopened.initialize(tx, owner=tx.owner)
            self.assertEqual(before, {p.name: p.stat().st_ino for p in root.iterdir()})

    def test_initial_slot_reservation_crash_refuses_unproven_bootstrap_cleanup(self):
        self.bootstrap_interruption("slot_reserved")

    def test_initial_partial_ownership_record_refuses_unproven_bootstrap_cleanup(self):
        self.bootstrap_interruption("partial_written")

    def test_initial_alias_creation_is_not_authority_until_replacement(self):
        self.bootstrap_interruption("linked")

    def test_initial_replacement_crash_has_authority_for_next_write(self):
        self.bootstrap_interruption("replaced", committed=True)
