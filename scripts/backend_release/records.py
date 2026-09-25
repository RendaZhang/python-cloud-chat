"""Versioned fixture records; serialization is pure and bounded, not a journal."""

from dataclasses import asdict, dataclass
import json

from .contracts import (
    FixturePaths,
    MAX_RECORD_BYTES,
    RequestIdentity,
    _fields,
    digest,
    fingerprint,
    integer,
    load_record,
    parse_release,
    require,
)
from .state import Transaction


@dataclass(frozen=True)
class Layout:
    device: int
    root_inode: int
    slot_a_inode: int
    slot_b_inode: int

    def __post_init__(self):
        integer(self.device, 0)
        for value in (self.root_inode, self.slot_a_inode, self.slot_b_inode):
            integer(value)
        require(
            len({self.root_inode, self.slot_a_inode, self.slot_b_inode}) == 3,
            "Duplicate fixture inode",
        )


def _release_record(release):
    value = asdict(release)
    del value["environment"]["fixtures"]
    value["code"]["files"] = sorted(
        value["code"]["files"], key=lambda item: item["path"]
    )
    value["environment"]["packages"] = sorted(
        value["environment"]["packages"], key=lambda item: item["name"]
    )
    value["code"]["runtime_digest"] = release.code.runtime_digest
    return value


@dataclass(frozen=True)
class Record:
    revision: int
    previous_digest: str | None
    clock_context: str
    lock_device: int
    lock_inode: int
    transaction: Transaction
    layout: Layout

    def __post_init__(self):
        integer(self.revision)
        require(
            (self.revision == 1) == (self.previous_digest is None),
            "Invalid predecessor",
        )
        if self.previous_digest is not None:
            digest(self.previous_digest)
        digest(self.clock_context)
        integer(self.lock_device, 0)
        integer(self.lock_inode)
        require(type(self.transaction) is Transaction, "Invalid transaction")
        require(type(self.layout) is Layout, "Invalid fixture layout")
        require(self.lock_device == self.layout.device, "Cross-device lock")
        require(
            self.lock_inode
            not in (
                self.layout.root_inode,
                self.layout.slot_a_inode,
                self.layout.slot_b_inode,
            ),
            "Lock aliases fixture layout",
        )

    def payload(self):
        tx = self.transaction
        return {
            "schema": 1,
            "revision": self.revision,
            "previous_digest": self.previous_digest,
            "clock_context": self.clock_context,
            "lock_device": self.lock_device,
            "lock_inode": self.lock_inode,
            "layout": asdict(self.layout),
            "transaction": {
                "baseline": _release_record(tx.baseline),
                "requested": _release_record(tx.requested),
                "source_checkout_sha": tx.source_checkout_sha,
                "kind": tx.kind,
                "phase": tx.phase,
                "started_at": tx.started_at,
                "last_at": tx.last_at,
                "failure": tx.failure,
            },
            "owner": asdict(tx.owner),
            "accepted_digest": tx.accepted.identity_digest,
            "serving_digest": tx.serving.identity_digest if tx.serving else None,
        }

    @property
    def identity_digest(self):
        return fingerprint(self.payload())

    @property
    def successful(self):
        return self.transaction.phase == "accepted"

    def encode(self):
        value = self.payload()
        value["record_digest"] = self.identity_digest
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        require(len(raw.encode("utf-8")) <= MAX_RECORD_BYTES, "Record bound exceeded")
        return raw.encode("utf-8")


def parse_record(raw: str, fixtures: FixturePaths) -> Record:
    value = _fields(
        load_record(raw),
        "schema revision previous_digest clock_context lock_device lock_inode "
        "transaction layout owner accepted_digest serving_digest record_digest",
    )
    integer(value["schema"], 1, 1)
    tx = _fields(
        value["transaction"],
        "baseline requested source_checkout_sha kind phase started_at last_at failure",
    )
    transaction = Transaction(
        parse_release(json.dumps(tx["baseline"]), fixtures),
        parse_release(json.dumps(tx["requested"]), fixtures),
        tx["source_checkout_sha"],
        tx["kind"],
        tx["phase"],
        tx["started_at"],
        tx["last_at"],
        tx["failure"],
    )
    owner = RequestIdentity(
        **_fields(value["owner"], "request_id run_id attempt generation")
    )
    result = Record(
        value["revision"],
        value["previous_digest"],
        value["clock_context"],
        value["lock_device"],
        value["lock_inode"],
        transaction,
        Layout(
            **_fields(value["layout"], "device root_inode slot_a_inode slot_b_inode")
        ),
    )
    require(owner == transaction.owner, "Owner does not match transaction")
    require(
        value["accepted_digest"] == transaction.accepted.identity_digest,
        "Accepted identity mismatch",
    )
    require(
        value["serving_digest"]
        == (transaction.serving.identity_digest if transaction.serving else None),
        "Serving identity mismatch",
    )
    digest(value["record_digest"])
    require(value["record_digest"] == result.identity_digest, "Record digest mismatch")
    return result
