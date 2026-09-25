"""Explicit POSIX temporary-fixture I/O only; no production entrypoint or recovery."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import PurePosixPath
import stat
import time

from .contracts import (
    ContractError,
    FixturePaths,
    MAX_RECORD_BYTES,
    RequestIdentity,
    digest,
    integer,
    require,
)
from .records import Layout, Record, parse_record
from .state import Transaction, deadline_decision, prepare, transition

STATE = "state.json"
LOCK = "owner.lock"
PENDING = "pending.json"
SLOTS = ("record-a.json", "record-b.json")
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class LockBusy(ContractError):
    """Bounded wait expired; never steal a lock or kill its holder."""


class ClockMismatch(ContractError):
    """No reset or reboot recovery is authorized by this fixture store."""


class DurabilityUncertain(ContractError):
    """Replacement may be visible but durable completion was not confirmed."""


def _identity(info):
    return info.st_dev, info.st_ino


def _regular(info, maximum, *, links=1):
    require(
        stat.S_ISREG(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_uid == os.geteuid()
        and (1 <= info.st_nlink <= 3 if links is None else info.st_nlink == links)
        and 0 <= info.st_size <= maximum,
        "Unsafe fixture file",
    )


class FixtureStore:
    def __init__(self, fixtures: FixturePaths, *, clock_context: str):
        require(type(fixtures) is FixturePaths, "Explicit fixture root required")
        digest(clock_context)
        # gettempdir() can write probe files on first use; constructors must not.
        temporary_prefixes = (
            "/tmp/",
            "/var/tmp/",
            "/private/tmp/",
            "/private/var/tmp/",
            "/private/var/folders/",
        )
        require(
            fixtures.root.startswith(temporary_prefixes),
            "Only an explicit temporary fixture is allowed",
        )
        self.fixtures = fixtures
        self.clock_context = clock_context
        self._chain_identity = None
        self._uncertain = False
        with self._directory() as chain:
            self._chain_identity = tuple(_identity(os.fstat(fd)) for fd, _ in chain)

    @contextmanager
    def _directory(self):
        chain = []
        try:
            chain.append((os.open("/", DIRECTORY_FLAGS), ""))
            for name in PurePosixPath(self.fixtures.root).parts[1:]:
                fd = os.open(name, DIRECTORY_FLAGS, dir_fd=chain[-1][0])
                chain.append((fd, name))
            self._validate_chain(chain)
            yield chain
        finally:
            for fd, _ in reversed(chain):
                os.close(fd)

    def _validate_chain(self, chain):
        identities = []
        for index, (fd, name) in enumerate(chain):
            info = os.fstat(fd)
            identities.append(_identity(info))
            require(stat.S_ISDIR(info.st_mode), "Fixture parent is not a directory")
            require(info.st_uid in (0, os.geteuid()), "Untrusted fixture parent")
            require(
                not info.st_mode & 0o022 or bool(info.st_mode & stat.S_ISVTX),
                "Writable non-sticky fixture parent",
            )
            if index:
                entry = os.stat(name, dir_fd=chain[index - 1][0], follow_symlinks=False)
                require(
                    _identity(entry) == _identity(info) and stat.S_ISDIR(entry.st_mode),
                    "Fixture path replaced",
                )
        root = os.fstat(chain[-1][0])
        require(
            root.st_uid == os.geteuid() and stat.S_IMODE(root.st_mode) == 0o700,
            "Fixture root must be private and owned",
        )
        require(
            self._chain_identity is None or self._chain_identity == tuple(identities),
            "Fixture directory identity changed",
        )

    def _entry_matches(self, directory, name, fd, maximum, *, links=1):
        opened = os.fstat(fd)
        entry = os.stat(name, dir_fd=directory, follow_symlinks=False)
        _regular(opened, maximum, links=links)
        _regular(entry, maximum, links=links)
        require(_identity(opened) == _identity(entry), "Fixture file replaced")
        return opened

    def _checkpoint(self, _stage):
        """Test subclasses synchronize only owned fault processes here."""

    @contextmanager
    def _locked(self, *, initialize=False, shared=False, wait_ms=250):
        integer(wait_ms, 0, 2000)
        require(
            shared or not self._uncertain, "Reopen required after uncertain persistence"
        )
        with self._directory() as chain:
            directory = chain[-1][0]
            if initialize:
                try:
                    fd = os.open(
                        LOCK,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | FILE_FLAGS,
                        0o600,
                        dir_fd=directory,
                    )
                except FileExistsError:
                    fd = os.open(LOCK, os.O_RDWR | FILE_FLAGS, dir_fd=directory)
            else:
                fd = os.open(
                    LOCK,
                    (os.O_RDONLY if shared else os.O_RDWR) | FILE_FLAGS,
                    dir_fd=directory,
                )
            try:
                self._entry_matches(directory, LOCK, fd, 0)
                expires = time.monotonic() + wait_ms / 1000
                while True:
                    try:
                        fcntl.flock(
                            fd,
                            (fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                            | fcntl.LOCK_NB,
                        )
                        break
                    except BlockingIOError:
                        remaining = expires - time.monotonic()
                        if remaining <= 0:
                            raise LockBusy("Fixture lock wait expired") from None
                        time.sleep(min(remaining, 0.01))
                self._validate_chain(chain)
                self._entry_matches(directory, LOCK, fd, 0)
                self._checkpoint("locked")
                if initialize:
                    os.fsync(fd)
                    os.fsync(directory)
                yield chain, fd
            finally:
                os.close(fd)  # Release flock, never unlink its permanent inode.

    def _layout(self, chain, lock_fd, record, *, initial=False):
        directory = chain[-1][0]
        self._validate_chain(chain)
        lock = self._entry_matches(directory, LOCK, lock_fd, 0)
        layout = record.layout
        require(
            _identity(os.fstat(directory)) == (layout.device, layout.root_inode),
            "Fixture root identity mismatch",
        )
        require(
            _identity(lock) == (record.lock_device, record.lock_inode),
            "Authoritative lock identity changed",
        )
        aliases = {}
        for name in (STATE, PENDING):
            try:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                require(name != STATE or initial, "Missing authoritative record")
            else:
                _regular(info, MAX_RECORD_BYTES, links=None)
                require(
                    info.st_dev == layout.device
                    and info.st_ino in (layout.slot_a_inode, layout.slot_b_inode),
                    "Unknown fixture alias",
                )
                aliases[name] = info.st_ino
        for name, inode in zip(SLOTS, (layout.slot_a_inode, layout.slot_b_inode)):
            fd = os.open(name, os.O_RDONLY | FILE_FLAGS, dir_fd=directory)
            try:
                links = 1 + sum(value == inode for value in aliases.values())
                info = self._entry_matches(
                    directory, name, fd, MAX_RECORD_BYTES, links=links
                )
                require(
                    _identity(info) == (layout.device, inode),
                    "Reserved slot identity changed",
                )
            finally:
                os.close(fd)
        return aliases

    def _read(self, chain, lock_fd):
        directory = chain[-1][0]
        fd = os.open(STATE, os.O_RDONLY | FILE_FLAGS, dir_fd=directory)
        try:
            before = self._entry_matches(
                directory, STATE, fd, MAX_RECORD_BYTES, links=None
            )
            self._checkpoint("read_opened")
            chunks, total = [], 0
            while chunk := os.read(fd, min(8192, MAX_RECORD_BYTES + 1 - total)):
                chunks.append(chunk)
                total += len(chunk)
                require(total <= MAX_RECORD_BYTES, "Record bound exceeded")
            after = self._entry_matches(
                directory, STATE, fd, MAX_RECORD_BYTES, links=None
            )
            require(
                (before.st_size, before.st_mtime_ns)
                == (after.st_size, after.st_mtime_ns),
                "Fixture record changed during read",
            )
            record = parse_record(b"".join(chunks).decode("utf-8"), self.fixtures)
        finally:
            os.close(fd)
        if record.clock_context != self.clock_context:
            raise ClockMismatch("Clock context changed; recovery is not implemented")
        self._layout(chain, lock_fd, record)
        return record

    def read(self, *, wait_ms=250):
        # Shared readers fence slot reuse, without creating or repairing any file.
        with self._locked(shared=True, wait_ms=wait_ms) as (chain, fd):
            return self._read(chain, fd)

    def deadline(self, *, owner: RequestIdentity, now: int):
        return deadline_decision(self.read().transaction, owner, now)

    def _compare(self, chain, lock_fd, expected):
        require(type(expected) is Record, "Expected prior record required")
        actual = self._read(chain, lock_fd)
        require(
            actual.revision == expected.revision
            and actual.identity_digest == expected.identity_digest,
            "Stale prior record",
        )
        return actual

    def _cleanup_pending(self, chain, lock_fd, record):
        aliases = self._layout(chain, lock_fd, record)
        if PENDING in aliases:
            directory = chain[-1][0]
            fd = os.open(PENDING, os.O_RDONLY | FILE_FLAGS, dir_fd=directory)
            try:
                info = self._entry_matches(
                    directory, PENDING, fd, MAX_RECORD_BYTES, links=None
                )
                require(info.st_ino == aliases[PENDING], "Pending alias changed")
                self._validate_chain(chain)
                self._entry_matches(directory, LOCK, lock_fd, 0)
                os.unlink(PENDING, dir_fd=directory)
                self._checkpoint("pending_removed")
                os.fsync(directory)
                self._checkpoint("pending_cleanup_synced")
            finally:
                os.close(fd)

    @staticmethod
    def _write_all(fd, raw):
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            require(count > 0, "Incomplete fixture write")
            offset += count

    def _commit(self, chain, lock_fd, record, expected, slot):
        raw = record.encode()
        directory = chain[-1][0]
        fd = os.open(slot, os.O_RDWR | FILE_FLAGS, dir_fd=directory)
        replaced = False
        replacement_attempted = False
        linked = False
        try:
            info = self._entry_matches(directory, slot, fd, MAX_RECORD_BYTES)
            inode = (
                record.layout.slot_a_inode
                if slot == SLOTS[0]
                else record.layout.slot_b_inode
            )
            require(
                _identity(info) == (record.layout.device, inode),
                "Reserved slot replaced",
            )
            os.ftruncate(fd, 0)
            self._checkpoint("slot_truncated")
            # The split is a deterministic partial-write fault boundary, not a commit.
            middle = len(raw) // 2
            self._write_all(fd, raw[:middle])
            self._checkpoint("partial_written")
            self._write_all(fd, raw[middle:])
            self._checkpoint("written")
            os.fsync(fd)
            self._checkpoint("file_synced")
            self._validate_chain(chain)
            self._entry_matches(directory, slot, fd, MAX_RECORD_BYTES)
            self._entry_matches(directory, LOCK, lock_fd, 0)
            if expected is not None:
                self._compare(chain, lock_fd, expected)
            else:
                require(
                    STATE not in self._layout(chain, lock_fd, record, initial=True),
                    "Already initialized",
                )
            os.link(
                slot,
                PENDING,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            linked = True
            self._checkpoint("linked")
            self._layout(chain, lock_fd, expected or record, initial=expected is None)
            self._entry_matches(directory, PENDING, fd, MAX_RECORD_BYTES, links=2)
            replacement_attempted = True
            os.replace(PENDING, STATE, src_dir_fd=directory, dst_dir_fd=directory)
            replaced = True
            self._checkpoint("replaced")
            os.fsync(directory)
            self._checkpoint("directory_synced")
            self._layout(chain, lock_fd, record)
        except Exception as error:
            if replacement_attempted:
                self._uncertain = True
                raise DurabilityUncertain(
                    "Fixture replacement durability uncertain"
                ) from error
            raise
        finally:
            try:
                if linked and not replaced:
                    entry = os.stat(PENDING, dir_fd=directory, follow_symlinks=False)
                    if _identity(entry) == _identity(os.fstat(fd)):
                        os.unlink(PENDING, dir_fd=directory)
                        os.fsync(directory)
            except FileNotFoundError:
                pass
            except OSError as error:
                self._uncertain = True
                raise DurabilityUncertain(
                    "Fixture cleanup durability uncertain"
                ) from error
            finally:
                os.close(fd)
        return record

    def initialize(self, transaction: Transaction, *, owner: RequestIdentity):
        require(
            type(transaction) is Transaction and transaction.phase == "prepared",
            "Initialize prepared state only",
        )
        require(
            type(owner) is RequestIdentity and owner == transaction.owner,
            "Wrong initial owner",
        )
        require(
            transaction.baseline.environment.fixtures == self.fixtures,
            "Fixture mismatch",
        )
        with self._locked(initialize=True) as (chain, fd):
            directory = chain[-1][0]
            for name in (STATE, PENDING, *SLOTS):
                try:
                    os.stat(name, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ContractError(
                        "Not an empty fixture; bootstrap repair is not automatic"
                    )
            slots = []
            try:
                for name in SLOTS:
                    slot_fd = os.open(
                        name,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | FILE_FLAGS,
                        0o600,
                        dir_fd=directory,
                    )
                    slots.append(slot_fd)
                    os.fsync(slot_fd)
                    self._checkpoint("slot_reserved")
                os.fsync(directory)
                root, lock = os.fstat(directory), os.fstat(fd)
                layout = Layout(
                    root.st_dev,
                    root.st_ino,
                    *(os.fstat(value).st_ino for value in slots),
                )
                record = Record(
                    1,
                    None,
                    self.clock_context,
                    lock.st_dev,
                    lock.st_ino,
                    transaction,
                    layout,
                )
                return self._commit(chain, fd, record, None, SLOTS[0])
            finally:
                for slot_fd in slots:
                    os.close(slot_fd)
                # Partial bootstrap has no durable ownership yet; never sweep it.

    def _persist(self, chain, lock_fd, actual, updated):
        record = Record(
            actual.revision + 1,
            actual.identity_digest,
            actual.clock_context,
            actual.lock_device,
            actual.lock_inode,
            updated,
            actual.layout,
        )
        record.encode()  # Bounds/validation before any cleanup or candidate write.
        self._cleanup_pending(chain, lock_fd, actual)
        aliases = self._layout(chain, lock_fd, actual)
        slot = SLOTS[1] if aliases[STATE] == actual.layout.slot_a_inode else SLOTS[0]
        return self._commit(chain, lock_fd, record, actual, slot)

    def advance(
        self, expected, owner, event, *, now, checks=None, failure=None, wait_ms=250
    ):
        with self._locked(wait_ms=wait_ms) as (chain, fd):
            actual = self._compare(chain, fd, expected)
            updated = transition(
                actual.transaction,
                owner,
                event,
                now=now,
                checks=checks,
                failure=failure,
            )
            return self._persist(chain, fd, actual, updated)

    def begin(
        self,
        expected,
        owner,
        requested,
        *,
        source_checkout_sha,
        kind="release",
        wait_ms=250,
    ):
        with self._locked(wait_ms=wait_ms) as (chain, fd):
            actual = self._compare(chain, fd, expected)
            tx = actual.transaction
            require(
                tx.phase in ("accepted", "recovered")
                or (tx.phase == "failed" and tx.started_at is None),
                "Prior transaction has not finished",
            )
            require(
                type(owner) is RequestIdentity and owner == requested.request,
                "Wrong new owner",
            )
            require(owner.generation > tx.owner.generation, "Stale generation")
            require(owner.request_id != tx.owner.request_id, "Reused request ID")
            require(
                tx.kind != "adoption" or tx.phase == "accepted" or kind == "adoption",
                "Adoption not accepted",
            )
            updated = prepare(
                tx.accepted,
                requested,
                source_checkout_sha=source_checkout_sha,
                kind=kind,
            )
            return self._persist(chain, fd, actual, updated)
