"""Disposable Linux CI capacity checkpoint, not a release builder or host adapter."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from email.parser import BytesParser

MIB = 1024 * 1024
MEMORY_LIMIT = 128 * MIB
PRODUCER_MEMORY_LIMIT = 256 * MIB
# Previous serial control-child ru_maxrss was 21,106,688 bytes and can include
# inherited pre-exec Python RSS. Reserve it honestly; do not subtract that cost.
CONTROL_ALLOWANCE = 32 * MIB
DISK_LIMITS = {
    "envs": 384 * MIB,
    "wheels": 256 * MIB,
    "workspace": 128 * MIB,
    "cache": 64 * MIB,
    "receipts": 64 * MIB,
}
TOTAL_LIMIT = 1280 * MIB
PRODUCER_DISK_LIMITS = {
    key: value for key, value in DISK_LIMITS.items() if key != "envs"
}
PRODUCER_TOTAL_LIMIT = 512 * MIB
ROOT_PREFIX = "backend-offline-proof-"
STAGES = (
    "tracked_inputs",
    "interpreter",
    "binary_download",
    "wheel_metadata",
    "artifact_packaging",
    "artifact_ingress",
    "artifact_verification",
    "network_isolation",
    "final_path_seed",
    "offline_install",
    "offline_verification",
)

_spec = importlib.util.spec_from_file_location(
    "preparation_artifact", Path(__file__).with_name("preparation_artifact.py")
)
artifact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(artifact)
EVENT_KEYS = ("low", "high", "max", "oom", "oom_kill", "oom_group_kill")
STAT_KEYS = (
    "anon",
    "file",
    "kernel",
    "kernel_stack",
    "pagetables",
    "sock",
    "shmem",
    "file_dirty",
    "file_writeback",
    "slab",
    "pgscan",
    "pgsteal",
)


class ProofError(ValueError):
    """Controlled diagnostic code; no secret or host configuration capture."""


def require(condition, code):
    if not condition:
        raise ProofError(code)


def sha256(file):
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pins(raw):
    require(len(raw) <= 65536, "requirements_too_large")
    result = {}
    for line in raw.decode("ascii").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9.+!-]+)", line)
        require(match is not None, "requirements_not_exact")
        name, version = match.groups()
        name = re.sub(r"[-_.]+", "-", name).lower()
        require(name not in result, "duplicate_requirement")
        result[name] = version
    require(len(result) == 73, "requirements_count_changed")
    return result


def allocated_tree(root):
    """Allocated blocks, unique inodes, regular files; never follow symlinks."""
    seen, allocated, files = set(), 0, 0
    if not root.exists():
        return {"allocated_bytes": 0, "inodes": 0, "files": 0}
    pending = [root]
    while pending:
        entry = pending.pop()
        try:
            info = entry.lstat()
        except FileNotFoundError:  # Concurrent installer scratch removal.
            continue
        key = info.st_dev, info.st_ino
        if key in seen:
            continue
        seen.add(key)
        allocated += info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode):
            try:
                pending.extend(entry.iterdir())
            except FileNotFoundError:
                pass
        elif stat.S_ISREG(info.st_mode):
            files += 1
    return {"allocated_bytes": allocated, "inodes": len(seen), "files": files}


def clean_environment(root):
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root / "workspace/home"),
        "TMPDIR": str(root / "workspace/tmp"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "PIP_CONFIG_FILE": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def normalized_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def member_label(name):
    return re.sub(r"[^A-Za-z0-9_./+-]", "?", name)[:160]


def hashed_requirements(wheel_directory, expected, diagnostics=None):
    """Checkpoint metadata/hash binding; pip still owns resolution and installation."""
    manifest, discovered, lines = [], {}, []
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update(wheels_checked=0, nested_metadata_total=0, nested_archives=[])
    wheels = sorted(wheel_directory.iterdir())
    require(len(wheels) <= 73, "wheel_count_bound")
    for wheel in wheels:
        info = wheel.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "wheel_not_regular")
        require(0 < info.st_size <= 256 * MIB, "wheel_size")
        require(len(wheel.name) <= 200, "wheel_filename")
        filename = re.fullmatch(
            r"([A-Za-z0-9_.]+)-([A-Za-z0-9_.+!]+)-(?:[0-9][A-Za-z0-9_.]*-)?"
            r"[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+\.whl",
            wheel.name,
        )
        require(filename is not None, "wheel_filename")
        with zipfile.ZipFile(wheel) as archive:
            metadata = [
                entry
                for entry in archive.infolist()
                if entry.filename.endswith(".dist-info/METADATA")
            ]
            root_metadata = [
                entry for entry in metadata if entry.filename.count("/") == 1
            ]
            nested = [entry for entry in metadata if entry.filename.count("/") != 1]
            detail = {
                "filename": wheel.name,
                "archive_member_count": len(archive.infolist()),
                "metadata_member_count": len(metadata),
                "root_metadata_count": len(root_metadata),
                "root_members": [
                    member_label(entry.filename) for entry in root_metadata[:2]
                ],
                "nested_metadata_count": len(nested),
                "nested_member_sample": [
                    member_label(entry.filename) for entry in nested[:3]
                ],
            }
            diagnostics["last_archive"] = detail
            diagnostics["nested_metadata_total"] += len(nested)
            if nested and len(diagnostics["nested_archives"]) < 8:
                diagnostics["nested_archives"].append(detail)
            require(len(root_metadata) == 1, "wheel_metadata")
            entry = root_metadata[0]
            identity = re.fullmatch(
                r"([A-Za-z0-9_.]+)-([A-Za-z0-9_.+!]+)\.dist-info/METADATA",
                entry.filename,
            )
            require(identity is not None, "wheel_metadata_identity")
            require(0 < entry.file_size <= MIB, "wheel_metadata_size")
            parsed = BytesParser().parsebytes(archive.read(entry))
        require(
            len(parsed.get_all("Name", [])) == 1
            and len(parsed.get_all("Version", [])) == 1,
            "wheel_metadata_headers",
        )
        name = normalized_name(parsed["Name"])
        version = parsed["Version"]
        require(
            normalized_name(filename[1]) == normalized_name(identity[1]) == name
            and filename[2] == identity[2] == version,
            "wheel_metadata_identity",
        )
        require(name not in discovered, "duplicate_wheel_project")
        require(expected.get(name) == version, "wheel_pin_mismatch")
        discovered[name] = version
        checksum = sha256(wheel)
        manifest.append(
            {
                "filename": wheel.name,
                "name": name,
                "version": version,
                "size": info.st_size,
                "sha256": checksum,
            }
        )
        lines.append(f"{name}=={version} --hash=sha256:{checksum}")
        diagnostics["wheels_checked"] += 1
    require(discovered == expected, "wheel_closure_mismatch")
    return manifest, "\n".join(lines) + "\n"


def command(
    args, *, root, timeout, offline=False, capture=False, extra_env=None, outcome=None
):
    if offline:
        args = ["/usr/bin/unshare", "--net", "--", *args]
    log = root / "workspace/command.log"
    with log.open("wb") as output:
        try:
            proc = subprocess.Popen(
                args,
                cwd=root,
                env={**clean_environment(root), **(extra_env or {})},
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as error:
            if outcome is not None:
                outcome.update(state="launch_failed", errno=bounded_errno(error))
            raise
        if outcome is not None:
            outcome["state"] = "started"
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                require(
                    not (root / "receipts/budget-exceeded").exists(),
                    "disk_budget_exceeded",
                )
                remaining = deadline - time.monotonic()
                require(remaining > 0, "child_deadline")
                try:
                    proc.wait(timeout=min(remaining, 0.1))
                except subprocess.TimeoutExpired:
                    pass
            code = proc.returncode
        finally:
            # Only the process group created above; no unrelated process matching.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=10)
            if outcome is not None:
                outcome.update(state="reaped", returncode=proc.returncode)
        require(log.stat().st_size <= MIB, "child_output_bound")
        if code:
            if outcome is None:
                print(log.read_text(errors="replace")[-4000:], flush=True)
            raise ProofError("child_exit_" + str(code))
        return log.read_text() if capture else None


BASE_PROBE = r"""
import ensurepip, hashlib, json, pathlib, platform, sys, sysconfig
seed = pathlib.Path(ensurepip.__file__).parent / '_bundled'
wheels = sorted(seed.glob('*.whl'))
assert len(wheels) == 1
print(json.dumps({
 'version': platform.python_version(), 'implementation': sys.implementation.name,
 'free_threaded': bool(sysconfig.get_config_var('Py_GIL_DISABLED')),
 'soabi': sysconfig.get_config_var('SOABI'), 'system': platform.system(),
 'architecture': platform.machine(), 'libc': platform.libc_ver(),
 'executable': str(pathlib.Path(sys.executable).resolve()),
 'seed_version': ensurepip.version(), 'seed_filename': wheels[0].name,
 'seed_sha256': hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
 'base_prefix': sys.base_prefix,
}))
"""

NETWORK_PROBE = r"""
import json, os, re, socket, sys
result = {
    'schema': 1, 'status': 'failed', 'code': 'unexpected_probe_error',
    'parent_namespace': int(sys.argv[1]), 'child_namespace': None,
    'interface_count': None, 'loopback_count': None,
    'connect_errnos': [], 'errno': None,
}
operation = 'namespace_read_failed'
try:
    identity = os.readlink('/proc/self/ns/net')
    match = re.fullmatch(r'net:\[([0-9]{1,20})\]', identity)
    if match is None or not 0 < int(match[1]) < 2**64:
        result['code'] = 'namespace_read_failed'
    else:
        result['child_namespace'] = int(match[1])
        if result['child_namespace'] == result['parent_namespace']:
            result['code'] = 'namespace_unchanged'
        else:
            operation = 'interface_query_failed'
            interfaces = socket.if_nameindex()
            result['interface_count'] = len(interfaces)
            result['loopback_count'] = sum(name == 'lo' for _, name in interfaces)
            if result['interface_count'] != 1 or result['loopback_count'] != 1:
                result['code'] = 'interfaces_not_loopback_only'
            else:
                operation = 'connect_probe_failed'
                for address in ('192.0.2.1', '1.1.1.1'):
                    with socket.socket() as sock:
                        sock.settimeout(1)
                        result['connect_errnos'].append(sock.connect_ex((address, 443)))
                if 0 in result['connect_errnos']:
                    result['code'] = 'external_connect_succeeded'
                else:
                    result.update(status='passed', code='ok')
except OSError as error:
    result['code'] = operation
    if type(error.errno) is int and 0 < error.errno <= 4095:
        result['errno'] = error.errno
except Exception:
    result['code'] = 'unexpected_probe_error'
print(json.dumps(result, separators=(',', ':'), allow_nan=False), flush=True)
raise SystemExit(0 if result['status'] == 'passed' else 1)
"""


def bounded_errno(error):
    value = getattr(error, "errno", None)
    return value if type(value) is int and 0 < value <= 4095 else None


def network_namespace_id():
    raw = os.readlink("/proc/self/ns/net")
    match = re.fullmatch(r"net:\[([0-9]{1,20})\]", raw)
    require(
        match is not None and 0 < int(match[1]) < 2**64, "namespace_identity_invalid"
    )
    return int(match[1])


def network_report_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "network_report_invalid")
        result[key] = value
    return result


def read_network_report(path, parent):
    try:
        with path.open("rb") as stream:
            raw = stream.read(2049)
    except FileNotFoundError:
        raise ProofError("network_report_missing") from None
    except OSError:
        raise ProofError("network_report_unreadable") from None
    require(len(raw) <= 2048, "network_report_oversized")
    require(raw.strip(), "network_report_missing")
    try:
        value = json.loads(raw, object_pairs_hook=network_report_object)
    except (ValueError, RecursionError):
        raise ProofError("network_report_invalid") from None
    codes = {
        "ok",
        "namespace_unchanged",
        "interfaces_not_loopback_only",
        "external_connect_succeeded",
        "namespace_read_failed",
        "interface_query_failed",
        "connect_probe_failed",
        "unexpected_probe_error",
    }
    require(
        isinstance(value, dict)
        and value.keys()
        == {
            "schema",
            "status",
            "code",
            "parent_namespace",
            "child_namespace",
            "interface_count",
            "loopback_count",
            "connect_errnos",
            "errno",
        },
        "network_report_invalid",
    )
    require(
        type(value["schema"]) is int
        and value["schema"] == 1
        and isinstance(value["code"], str)
        and value["code"] in codes
        and value["status"] == ("passed" if value["code"] == "ok" else "failed")
        and type(value["parent_namespace"]) is int
        and value["parent_namespace"] == parent,
        "network_report_invalid",
    )
    for key, minimum, maximum in (
        ("child_namespace", 1, 2**64 - 1),
        ("interface_count", 0, 65535),
        ("loopback_count", 0, 65535),
        ("errno", 1, 4095),
    ):
        field = value[key]
        require(
            field is None or (type(field) is int and minimum <= field <= maximum),
            "network_report_invalid",
        )
    errnos = value["connect_errnos"]
    require(
        isinstance(errnos, list)
        and len(errnos) <= 2
        and all(type(code) is int and 0 <= code <= 4095 for code in errnos),
        "network_report_invalid",
    )
    if value["status"] == "passed":
        require(
            value["child_namespace"] is not None
            and value["child_namespace"] != parent
            and value["interface_count"] == value["loopback_count"] == 1
            and len(errnos) == 2
            and all(errnos)
            and value["errno"] is None,
            "network_report_invalid",
        )
    if value["code"] == "namespace_unchanged":
        require(value["child_namespace"] == parent, "network_report_invalid")
    elif value["code"] == "interfaces_not_loopback_only":
        require(
            value["interface_count"] is not None
            and value["loopback_count"] is not None
            and (value["interface_count"], value["loopback_count"]) != (1, 1),
            "network_report_invalid",
        )
    elif value["code"] == "external_connect_succeeded":
        require(len(errnos) == 2 and 0 in errnos, "network_report_invalid")
    return value


def prove_network_isolation(base, root, receipt):
    # Retain only validated facts, including on nonzero exit, before owner cleanup.
    diagnostic = {"status": "failed", "failure": "unknown"}
    receipt["network"] = diagnostic
    outcome = {"state": "not_started", "returncode": None, "errno": None}
    diagnostic["command"] = outcome
    try:
        try:
            parent = network_namespace_id()
        except (OSError, ProofError) as error:
            diagnostic.update(
                failure="parent_namespace_unavailable", errno=bounded_errno(error)
            )
            raise ProofError("network_isolation_failed") from None
        diagnostic["parent_namespace"] = parent
        command_failed = False
        try:
            command(
                [str(base), "-I", "-B", "-c", NETWORK_PROBE, str(parent)],
                root=root,
                timeout=10,
                offline=True,
                outcome=outcome,
            )
        except Exception as error:
            command_failed = True
            diagnostic["command_failure"] = (
                str(error)
                if isinstance(error, ProofError)
                and str(error)
                in {
                    "child_deadline",
                    "child_output_bound",
                    "disk_budget_exceeded",
                }
                else "command_failed"
            )
        if outcome["state"] in ("started", "reaped"):
            try:
                diagnostic["probe"] = read_network_report(
                    root / "workspace/command.log", parent
                )
                diagnostic["report_status"] = "valid"
            except ProofError as error:
                diagnostic["report_status"] = str(error)
        else:
            diagnostic["report_status"] = "not_started"
        report = diagnostic.get("probe")
        if outcome["state"] == "launch_failed":
            diagnostic["failure"] = "launch_failed"
        elif report is not None and report["status"] == "failed":
            diagnostic["failure"] = (
                "probe_invariant_failed"
                if report["code"]
                in {
                    "namespace_unchanged",
                    "interfaces_not_loopback_only",
                    "external_connect_succeeded",
                }
                else "probe_reported_failure"
            )
        elif (
            command_failed or outcome["state"] != "reaped" or outcome["returncode"] != 0
        ):
            diagnostic["failure"] = "child_failed_unknown"
        elif report is None:
            diagnostic["failure"] = "report_unavailable"
        else:
            diagnostic.update(status="passed", failure=None)
    finally:
        write_receipt(root, receipt)
    require(diagnostic["status"] == "passed", "network_isolation_failed")


INVENTORY_PROBE = r"""
import importlib, importlib.metadata, json, pathlib, re, sys
names = {}
for dist in importlib.metadata.distributions():
    name = re.sub(r'[-_.]+', '-', dist.metadata['Name']).lower()
    assert name not in names
    names[name] = dist.version
modules = ('gevent', 'greenlet', '_cffi_backend', 'cryptography.hazmat.bindings._rust',
 'psycopg2._psycopg', 'pydantic_core._pydantic_core', 'aiohttp._http_parser',
 'frozenlist', 'multidict', 'propcache', 'yarl', 'jiter', 'msgspec', 'psutil',
 'yaml._yaml', 'markupsafe', 'charset_normalizer', 'sqlalchemy.cyextension',
 'zope.interface', '_argon2_cffi_bindings')
for module in modules:
    importlib.import_module(module)
assert 'app' not in sys.modules and 'app_auth' not in sys.modules
config = (pathlib.Path(sys.prefix) / 'pyvenv.cfg').read_text()
assert 'include-system-site-packages = false' in config.splitlines()
entrypoints = {}
for name in ('pip', 'gunicorn'):
    with (pathlib.Path(sys.prefix) / 'bin' / name).open() as stream:
        entrypoints[name] = stream.readline(512).strip()
    assert entrypoints[name] == '#!' + sys.executable
print(json.dumps({'packages': names, 'native_imports': list(modules),
 'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'entrypoints': entrypoints,
 'base_executable': str(pathlib.Path(sys._base_executable).resolve())}))
"""


def verify_base(base, root):
    require(
        base.is_absolute() and base == base.resolve(strict=True), "base_not_realpath"
    )
    info = base.lstat()
    require(
        stat.S_ISREG(info.st_mode) and os.access(base, os.X_OK), "base_not_executable"
    )
    require(not base.is_relative_to(root), "base_must_be_separate_read_only_input")
    before = sha256(base)
    data = json.loads(
        command(
            [str(base), "-I", "-B", "-c", BASE_PROBE],
            root=root,
            timeout=10,
            capture=True,
        )
    )
    require(
        data["version"] == "3.13.14"
        and data["implementation"] == "cpython"
        and not data["free_threaded"]
        and data["soabi"].startswith("cpython-313-")
        and data["system"] == "Linux"
        and data["architecture"] == "x86_64"
        and data["libc"][0] == "glibc"
        and data["executable"] == str(base),
        "base_runtime_mismatch",
    )
    require(before == sha256(base), "base_changed_during_probe")
    return dict(data, binary_sha256=before, access="read-only-input")


def memory_snapshot(cgroup):
    result = {}
    for metric in (
        "memory.current",
        "memory.peak",
        "memory.swap.peak",
        "memory.events",
        "memory.stat",
    ):
        with (cgroup / metric).open() as stream:
            raw = stream.read(16385)
        require(len(raw) <= 16384, "cgroup_metric_bound")
        if metric in ("memory.events", "memory.stat"):
            keys = EVENT_KEYS if metric == "memory.events" else STAT_KEYS
            values = {}
            for line in raw.splitlines():
                key, value = line.split()
                if key in keys:
                    require(
                        key not in values and value.isdecimal(), "cgroup_metric_invalid"
                    )
                    values[key] = int(value)
            required = (
                ("max", "oom", "oom_kill")
                if metric == "memory.events"
                else ("anon", "file", "kernel")
            )
            require(set(required) <= values.keys(), "cgroup_metric_missing")
            result[metric] = values
        else:
            require(raw.strip().isdecimal(), "cgroup_metric_invalid")
            result[metric] = int(raw)
    return result


def memory_failures(memory, limit=MEMORY_LIMIT):
    if not isinstance(memory, dict) or any(
        type(memory.get(key)) is not int or memory[key] < 0
        for key in ("memory.current", "memory.peak", "memory.swap.peak")
    ):
        return {"invalid_live_memory_evidence"}
    events = memory.get("memory.events")
    if (
        not isinstance(events, dict)
        or not {"max", "oom", "oom_kill"} <= events.keys()
        or any(type(value) is not int or value < 0 for value in events.values())
    ):
        return {"invalid_live_memory_evidence"}
    failures = set()
    if memory["memory.peak"] > limit or memory["memory.current"] > limit:
        failures.add("measured_memory_budget_exceeded")
    if memory["memory.swap.peak"] != 0:
        failures.add("measured_swap_budget_exceeded")
    if any(
        memory["memory.events"].get(key, 0)
        for key in ("oom", "oom_kill", "oom_group_kill")
    ):
        failures.add("memory_oom_event")
    return failures


def wait_for_owned_writers(cgroup, *, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        pids = (cgroup / "cgroup.procs").read_text().split()
        if pids == [str(os.getpid())]:
            return
        require(time.monotonic() < deadline, "owned_writers_remain")
        time.sleep(0.05)


class Meter:
    def __init__(
        self,
        root,
        cgroup,
        *,
        memory_limit=MEMORY_LIMIT,
        disk_limits=None,
        total_limit=TOTAL_LIMIT,
    ):
        self.root, self.cgroup = root, cgroup
        self.memory_limit = memory_limit
        self.disk_limits = DISK_LIMITS if disk_limits is None else disk_limits
        self.total_limit = total_limit
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.high_water = {}
        self.samples = 0
        self.max_sample_gap_seconds = 0
        self.previous_sample = time.monotonic()
        self.failure = None
        self.resource_failures = set()
        self.stages = {}
        self.stage = None
        self.stage_started = None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def once(self):
        with self.lock:
            usage = {
                name: allocated_tree(self.root / name) for name in self.disk_limits
            }
            usage["total"] = allocated_tree(self.root)
            memory = memory_snapshot(self.cgroup)
            now = time.monotonic()
            self.max_sample_gap_seconds = max(
                self.max_sample_gap_seconds, now - self.previous_sample
            )
            self.previous_sample = now
            self.samples += 1
            self.update_high_water(self.high_water, usage)
            self.resource_failures.update(memory_failures(memory, self.memory_limit))
            if self.stage is not None:
                stage = self.stages[self.stage]
                stage.setdefault("memory_start", memory)
                stage["memory_latest"] = memory
                stage["duration_seconds"] = now - self.stage_started
                stage["samples"] += 1
                if memory["memory.current"] >= stage["sampled_current_high_water"]:
                    stage["sampled_current_high_water"] = memory["memory.current"]
                    stage["stat_at_sampled_current_high_water"] = memory["memory.stat"]
                self.update_high_water(stage["sampled_disk_high_water"], usage)
            resources = {
                "sampled_disk_high_water": self.high_water,
                "samples": self.samples,
                "max_sample_gap_seconds": self.max_sample_gap_seconds,
                "elapsed_seconds": now - self.started,
                "active_stage": self.stage,
                "stages": self.stages,
                "resource_failures": sorted(self.resource_failures),
                **memory,
            }
            # Keep bounded crash evidence even if the cgroup kills the worker.
            pending = self.root / "receipts/resource-pending.json"
            raw = json.dumps(resources, sort_keys=True)
            require(len(raw.encode()) <= 65536, "resource_receipt_bound")
            pending.write_text(raw)
            os.replace(pending, self.root / "receipts/resources.json")
        for name, limit in {**self.disk_limits, "total": self.total_limit}.items():
            require(usage[name]["allocated_bytes"] <= limit, "disk_budget_" + name)

    @staticmethod
    def update_high_water(high_water, usage):
        for name, values in usage.items():
            prior = high_water.setdefault(name, dict.fromkeys(values, 0))
            for key, value in values.items():
                prior[key] = max(prior[key], value)

    def begin(self, name):
        require(name in STAGES and name not in self.stages, "stage_not_unique_or_known")
        self.once()
        with self.lock:
            if self.stage is not None:
                self.stages[self.stage]["ended"] = True
            self.stage = name
            self.stage_started = time.monotonic()
            self.stages[name] = {
                "samples": 0,
                "sampled_current_high_water": 0,
                "sampled_disk_high_water": {},
                "ended": False,
            }
        self.once()

    def check_limits(self):
        self.once()
        require(self.failure is None, "sampling_failed")
        require(not self.resource_failures, ",".join(sorted(self.resource_failures)))

    def _sample(self):
        while not self.stop.is_set():
            try:
                self.once()
            except Exception as error:
                self.failure = type(error).__name__ + ":" + str(error)
                (self.root / "receipts/budget-exceeded").touch()
                return
            self.stop.wait(0.1)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=10)
        require(not self.thread.is_alive(), "meter_not_reaped")
        self.once()
        require(self.failure is None, "sampling_failed")
        with self.lock:
            if self.stage is not None:
                self.stages[self.stage]["ended"] = True
        self.check_limits()
        return self.high_water


def write_receipt(root, receipt):
    destination = root / "receipts/worker.json"
    raw = json.dumps(receipt, sort_keys=True, indent=2).encode()
    require(len(raw) <= 65536, "receipt_bound")
    with destination.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def enter_stage(root, receipt, meter, name, *, diagnostic=False):
    # Only bounded metadata diagnosis may follow an already measured overrun.
    if not diagnostic:
        meter.check_limits()
    meter.begin(name)
    receipt["stage"] = name
    write_receipt(root, receipt)


def diagnose_wheels(root, expected, receipt, meter):
    enter_stage(root, receipt, meter, "wheel_metadata", diagnostic=True)
    receipt["metadata_diagnostics"] = {}
    try:
        manifest, hashed = hashed_requirements(
            root / "wheels", expected, receipt["metadata_diagnostics"]
        )
        receipt["wheel_files"] = manifest
        receipt["metadata_status"] = "passed"
    except Exception as error:
        receipt["metadata_status"] = "failed"
        receipt["metadata_failure"] = (
            str(error) if isinstance(error, ProofError) else type(error).__name__
        )
        raise
    finally:
        write_receipt(root, receipt)
        meter.check_limits()
    return hashed


def worker(root, base, repository, target_sha, role="consumer"):
    require(
        sys.platform == "linux" and os.geteuid() == 0, "disposable_linux_root_required"
    )
    require(
        root.parent == Path("/tmp") and root.name.startswith(ROOT_PREFIX),
        "fixture_root",
    )
    root.mkdir(mode=0o700)
    identity = root.stat()
    require(root == root.resolve(), "private_root")
    disk_limits = PRODUCER_DISK_LIMITS if role == "producer" else DISK_LIMITS
    total_limit = PRODUCER_TOTAL_LIMIT if role == "producer" else TOTAL_LIMIT
    aggregate = PRODUCER_MEMORY_LIMIT if role == "producer" else MEMORY_LIMIT
    service_limit = aggregate - CONTROL_ALLOWANCE
    for name in disk_limits:
        (root / name).mkdir(mode=0o700)
    for name in ("home", "tmp"):
        (root / "workspace" / name).mkdir(mode=0o700)
    relative = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
    require(ROOT_PREFIX in relative, "owned_cgroup_required")
    cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
    require(
        int((cgroup / "memory.max").read_text()) == service_limit,
        "memory_limit_missing",
    )
    require(int((cgroup / "memory.swap.max").read_text()) == 0, "swap_limit_missing")
    receipt = {
        "scope": "disposable-linux-split-checkpoint",
        "status": "running",
        "role": role,
        "source_sha": target_sha,
        "protected_environment_count": 0,
        "aggregate_budget": aggregate,
        "service_memory_limit": service_limit,
        "external_serial_control_allowance": CONTROL_ALLOWANCE,
        "disk_limits": disk_limits,
        "total_disk_limit": total_limit,
        "cleanup": "pending",
    }
    meter = Meter(
        root,
        cgroup,
        memory_limit=service_limit,
        disk_limits=disk_limits,
        total_limit=total_limit,
    )
    meter.thread.start()
    try:
        enter_stage(root, receipt, meter, "tracked_inputs")
        raw = command(
            [
                "/usr/bin/git",
                "-c",
                f"safe.directory={repository}",
                "-C",
                str(repository),
                "show",
                target_sha + ":requirements.txt",
            ],
            root=root,
            timeout=10,
            capture=True,
        ).encode("ascii")
        pins(raw)
        (root / "workspace/requirements.txt").write_bytes(raw)
        enter_stage(root, receipt, meter, "interpreter")
        receipt["base"] = verify_base(base, root)
        requirements = root / "workspace/requirements.txt"
        expected = pins(requirements.read_bytes())
        receipt["requirements_sha256"] = sha256(requirements)
        receipt["pin_count"] = len(expected)
        receipt["base"]["pip_version"] = json.loads(
            command(
                [
                    str(base),
                    "-I",
                    "-B",
                    "-c",
                    "import pip,json; print(json.dumps(pip.__version__))",
                ],
                root=root,
                timeout=10,
                capture=True,
            )
        )
        if role == "producer":
            enter_stage(root, receipt, meter, "binary_download")
            command(
                [
                    str(base),
                    "-I",
                    "-B",
                    "-m",
                    "pip",
                    "--isolated",
                    "--disable-pip-version-check",
                    "download",
                    "--only-binary=:all:",
                    "--no-cache-dir",
                    "--progress-bar=off",
                    "--retries=0",
                    "--timeout=20",
                    "--index-url=https://pypi.org/simple",
                    "--dest",
                    str(root / "wheels"),
                    "--requirement",
                    str(requirements),
                ],
                root=root,
                timeout=300,
            )
            diagnose_wheels(root, expected, receipt, meter)
            enter_stage(root, receipt, meter, "artifact_packaging")
            manifest = {
                "schema": 1,
                "source_sha": target_sha,
                "requirements_sha256": receipt["requirements_sha256"],
                "run_id": os.environ["GITHUB_RUN_ID"],
                "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                "producer": receipt["base"],
                "wheels": receipt["wheel_files"],
            }
            bundle = artifact.create_bundle(root / "wheels", manifest)
            receipt["bundle_sha256"] = sha256(bundle)
            require(
                sha256(base) == receipt["base"]["binary_sha256"], "base_binary_changed"
            )
            meter.check_limits()
            receipt["status"] = "wheel_producer_passed_not_release_ready"
            return
        enter_stage(root, receipt, meter, "artifact_ingress")
        transport_env = {
            name: os.environ[name]
            for name in (
                "GH_ARTIFACT_TOKEN",
                "ARTIFACT_REPOSITORY",
                "ARTIFACT_ID",
                "ARTIFACT_DIGEST",
                "GITHUB_RUN_ID",
                "GITHUB_SHA",
            )
        }
        command(
            [
                "/usr/bin/python3",
                "-I",
                "-B",
                str(Path(artifact.__file__).resolve()),
                str(root / "wheels"),
            ],
            root=root,
            timeout=120,
            extra_env=transport_env,
        )
        transport_env.clear()
        os.environ.pop("GH_ARTIFACT_TOKEN", None)
        enter_stage(root, receipt, meter, "artifact_verification")
        manifest, receipt["manifest_sha256"] = artifact.unpack_bundle(
            root / "wheels",
            source_sha=target_sha,
            requirements_sha=receipt["requirements_sha256"],
            run_id=os.environ["GITHUB_RUN_ID"],
            attempt=os.environ["GITHUB_RUN_ATTEMPT"],
            base=receipt["base"],
        )
        hashed = diagnose_wheels(root, expected, receipt, meter)
        require(
            receipt["wheel_files"] == manifest["wheels"], "artifact_metadata_mismatch"
        )
        locked = root / "workspace/install.txt"
        locked.write_text(hashed)
        enter_stage(root, receipt, meter, "network_isolation")
        prove_network_isolation(base, root, receipt)
        enter_stage(root, receipt, meter, "final_path_seed")
        final = root / "envs/candidate"
        require(not final.exists(), "final_path_already_exists")
        command(
            [str(base), "-I", "-B", "-m", "venv", str(final)],
            root=root,
            timeout=60,
            offline=True,
        )
        python = str(final / "bin/python")
        enter_stage(root, receipt, meter, "offline_install")
        command(
            [
                python,
                "-I",
                "-B",
                "-m",
                "pip",
                "--isolated",
                "--disable-pip-version-check",
                "install",
                "--no-index",
                "--no-deps",
                "--find-links",
                str(root / "wheels"),
                "--require-hashes",
                "--only-binary=:all:",
                "--no-cache-dir",
                "--no-compile",
                "--progress-bar=off",
                "--requirement",
                str(locked),
            ],
            root=root,
            timeout=180,
            offline=True,
        )
        enter_stage(root, receipt, meter, "offline_verification")
        command(
            [python, "-I", "-B", "-m", "pip", "--isolated", "check"],
            root=root,
            timeout=30,
            offline=True,
        )
        installed = json.loads(
            command(
                [python, "-I", "-B", "-c", INVENTORY_PROBE],
                root=root,
                timeout=30,
                offline=True,
                capture=True,
            )
        )
        require(
            installed["packages"]
            == dict(expected, pip=receipt["base"]["seed_version"]),
            "inventory_mismatch",
        )
        require(
            installed["prefix"] == str(final)
            and installed["base_executable"] == str(base)
            and installed["base_prefix"] == receipt["base"]["base_prefix"],
            "environment_identity_mismatch",
        )
        receipt["installed"] = installed
        require(sha256(base) == receipt["base"]["binary_sha256"], "base_binary_changed")
        meter.check_limits()
        receipt["status"] = "offline_consumer_passed_not_release_ready"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["failure"] = (
            str(error)
            if isinstance(error, (ProofError, artifact.ArtifactError))
            else type(error).__name__
        )
        raise
    finally:
        try:
            receipt["sampled_high_water"] = meter.finish()
        except Exception as error:
            receipt["status"] = "failed"
            receipt["resource_failure"] = (
                str(error) if isinstance(error, ProofError) else type(error).__name__
            )
            raise
        finally:
            latest = memory_snapshot(cgroup)
            receipt.update(latest)
            final_failures = memory_failures(latest, service_limit)
            if final_failures:
                receipt["status"] = "failed"
                receipt["resource_failure"] = ",".join(sorted(final_failures))
            receipt["disk_measurement"] = (
                "nominal 100ms samples plus final check; actual sample gaps recorded; not disk quotas"
            )
            write_receipt(root, receipt)
            # No surviving command writers: command() always kills/reaps its owned group.
            # Unknown identities preserve the fixture. CI observer only collects evidence.
            wait_for_owned_writers(cgroup)
            owned_cleanup(
                root,
                identity,
                receipt,
                keep_bundle=role == "producer"
                and receipt["status"] == "wheel_producer_passed_not_release_ready",
            )
            receipt.update(memory_snapshot(cgroup))
            final_failures.update(memory_failures(receipt, service_limit))
            if final_failures:
                receipt["status"] = "failed"
                receipt["resource_failure"] = ",".join(sorted(final_failures))
            write_receipt(root, receipt)
            require(not final_failures, ",".join(sorted(final_failures)))
            if (
                role == "producer"
                and receipt["status"] == "wheel_producer_passed_not_release_ready"
            ):
                # Publish only the public bundle to the unprivileged CI upload relay.
                (root / "wheels/bundle.zip").chmod(0o644)
                (root / "wheels").chmod(0o711)
                root.chmod(0o711)


def owned_cleanup(root, identity, receipt, *, keep_bundle=False):
    current = root.lstat()
    require(
        stat.S_ISDIR(current.st_mode)
        and current.st_dev == identity.st_dev
        and current.st_ino == identity.st_ino
        and current.st_uid == os.geteuid()
        and stat.S_IMODE(current.st_mode) == 0o700,
        "cleanup_identity_uncertain",
    )
    require(
        set(path.name for path in root.iterdir()) <= set(DISK_LIMITS),
        "cleanup_unknown_path",
    )
    for name in DISK_LIMITS:
        path = root / name
        if not path.exists():
            continue
        require(path.is_dir() and not path.is_symlink(), "cleanup_component_uncertain")
        if name == "receipts":
            continue
        if name == "wheels" and keep_bundle:
            for file in path.iterdir():
                if file.name != "bundle.zip":
                    file.unlink()
        else:
            shutil.rmtree(path)
    receipt["cleanup"] = "owned_incomplete_paths_removed_receipts_retained"


def read_optional_receipt(file):
    if not file.exists():
        return {"status": "missing"}
    try:
        require(file.stat().st_size <= 65536, "receipt_bound")
        value = json.loads(file.read_text())
        require(isinstance(value, dict), "receipt_not_object")
        return value
    except (ValueError, OSError, UnicodeError):
        return {"status": "invalid_or_interrupted"}


def unit_properties(unit):
    show = subprocess.run(
        [
            "systemctl",
            "show",
            unit,
            "--property=LoadState,Result,MemoryPeak,MemorySwapPeak,MainPID,ControlGroup,ActiveState,ExecMainStatus",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    require(show.returncode == 0, "unit_status_unavailable")
    return dict(line.split("=", 1) for line in show.stdout.splitlines() if "=" in line)


def post_exit_memory_peak(properties):
    """An unloaded unit's optional observation cannot stand in for live evidence."""
    require(isinstance(properties, dict), "post_exit_memory_peak_invalid")
    if "MemoryPeak" not in properties:
        return {"status": "unavailable", "reason": "missing"}
    raw = properties["MemoryPeak"]
    if raw == "[not set]":
        return {"status": "unavailable", "reason": "not_set"}
    require(
        isinstance(raw, str) and re.fullmatch(r"[0-9]{1,20}", raw) is not None,
        "post_exit_memory_peak_invalid",
    )
    value = int(raw)
    require(value <= 2**64 - 1, "post_exit_memory_peak_invalid")
    return {"status": "available", "bytes": value}


def controller(base, repository, target_sha, output, role="consumer"):
    """CI-only launcher/evidence observer; all actual preparation stays in the unit."""
    require(os.environ.get("GITHUB_ACTIONS") == "true", "github_runner_only")
    require(
        sys.platform == "linux" and os.geteuid() == 0, "disposable_linux_root_required"
    )
    require(
        'VERSION_ID="24.04"' in Path("/etc/os-release").read_text(),
        "ubuntu_24_required",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", target_sha), "exact_sha_required")
    # Reserve a unique pathname, but let the metered service create its own fixture.
    root = Path(tempfile.mkdtemp(prefix=ROOT_PREFIX, dir="/tmp"))
    root.rmdir()
    unit = root.name + ".service"
    aggregate = PRODUCER_MEMORY_LIMIT if role == "producer" else MEMORY_LIMIT
    receipt = {
        "source_sha": target_sha,
        "unit": unit,
        "role": role,
        "memory_limit": aggregate,
        "service_limit": aggregate - CONTROL_ALLOWANCE,
        "external_serial_control_allowance": CONTROL_ALLOWANCE,
        "swap_limit": 0,
        "protected_environment_count": 0,
        "not_proved": [
            "immutable_release_publication",
            "protected_environment_reuse",
            "production_host_capacity",
            "ci_observer_and_artifact_upload_relay_aggregate",
        ],
        "production_identity": False,
        "cleanup": "pending",
    }
    proc = None
    try:
        args = [
            "systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--unit=" + unit,
            "--property=MemoryAccounting=yes",
            "--property=MemoryMax=" + str(aggregate - CONTROL_ALLOWANCE),
            "--property=MemorySwapMax=0",
            "--property=TasksMax=64",
            "--property=RuntimeMaxSec=650",
            "--property=TimeoutStopSec=10",
            "--property=KillMode=control-group",
            "--property=Type=exec",
        ]
        environment_keys = ["GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"]
        if role == "consumer":
            environment_keys += [
                "GH_ARTIFACT_TOKEN",
                "ARTIFACT_REPOSITORY",
                "ARTIFACT_ID",
                "ARTIFACT_DIGEST",
                "GITHUB_SHA",
            ]
        # --setenv=NAME inherits without exposing values in process arguments/logs.
        args += ["--setenv=" + name for name in environment_keys]
        args += [
            "/usr/bin/python3",
            "-I",
            "-B",
            str(Path(__file__).resolve()),
            "worker",
            "--root",
            str(root),
            "--base",
            str(base),
            "--repository",
            str(repository),
            "--sha",
            target_sha,
            "--role",
            role,
        ]
        proc = subprocess.Popen(
            args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        receipt["unit_returncode"] = proc.wait(timeout=680)
    except Exception as error:
        receipt["controller_failure"] = type(error).__name__
    finally:
        try:
            if proc is not None:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
            receipt["launcher_reaped"] = True
            receipt["systemd"] = unit_properties(unit)
            group = receipt["systemd"].get("ControlGroup", "")
            require(
                not group or (group.startswith("/") and ROOT_PREFIX in group),
                "unexpected_owned_cgroup",
            )
            cgroup = Path("/sys/fs/cgroup") / group.lstrip("/")
            if group and (cgroup / "memory.peak").exists():
                receipt["unit_final_memory"] = memory_snapshot(cgroup)
            if receipt["systemd"].get("LoadState") != "not-found":
                subprocess.run(["systemctl", "stop", unit], timeout=15, check=True)
            remaining = unit_properties(unit)
            require(remaining.get("MainPID") == "0", "owned_processes_not_reaped")
            procs = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
            require(
                not group or not procs.exists() or not procs.read_text().strip(),
                "owned_descendants_remain",
            )
            subprocess.run(
                ["systemctl", "reset-failed", unit],
                timeout=10,
                check=False,
                capture_output=True,
            )
            receipt["cleanup"] = "owned_unit_stopped_mainpid_zero_cgroup_empty"
        except Exception as error:
            receipt["cleanup"] = "failed_fixture_preserved"
            receipt["cleanup_failure"] = (
                str(error) if isinstance(error, ProofError) else type(error).__name__
            )
        receipt["worker"] = read_optional_receipt(root / "receipts/worker.json")
        receipt["last_resources"] = read_optional_receipt(
            root / "receipts/resources.json"
        )
        receipt["final_allocation_before_cleanup"] = allocated_tree(root)
        controls_peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024
        receipt["outside_ci_observer"] = {
            "controller_peak_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            * 1024,
            "measurement": "CI-only evidence collector RSS, not a target controller or aggregate hard limit; upload-artifact relay not measured",
        }
        receipt["external_serial_controls_peak_rss_bytes"] = controls_peak
        receipt["controls_within_allowance"] = controls_peak <= CONTROL_ALLOWANCE
        receipt["control_accounting"] = (
            "serial systemd-run/systemctl children; summed conservative RSS ceiling with service cap, "
            "not simultaneous measured aggregate; shared system manager kernel/baseline cost remains unproved"
        )
        receipt["retained_fixture"] = str(root)
        try:
            receipt["post_exit_memory_peak"] = post_exit_memory_peak(
                receipt.get("systemd", {})
            )
        except ProofError as error:
            receipt["post_exit_memory_peak"] = {
                "status": "invalid",
                "failure": str(error),
            }
        # The observer never sweeps interrupted files. Only the metered owner cleans.
        output.mkdir(mode=0o755, parents=True, exist_ok=True)
        raw_receipt = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        require(len(raw_receipt.encode()) <= 65536, "controller_receipt_bound")
        (output / "capacity.json").write_text(raw_receipt)
        print(raw_receipt, flush=True)
        if (
            role == "producer"
            and receipt["worker"].get("status")
            == "wheel_producer_passed_not_release_ready"
        ):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
                stream.write(f"bundle={root}/wheels/bundle.zip\n")
    require(
        receipt.get("unit_returncode") == 0
        and "controller_failure" not in receipt
        and receipt["worker"].get("status")
        == (
            "wheel_producer_passed_not_release_ready"
            if role == "producer"
            else "offline_consumer_passed_not_release_ready"
        )
        and receipt["cleanup"] == "owned_unit_stopped_mainpid_zero_cgroup_empty"
        and receipt["worker"].get("cleanup")
        == "owned_incomplete_paths_removed_receipts_retained"
        and receipt["controls_within_allowance"]
        and not memory_failures(receipt["worker"], aggregate - CONTROL_ALLOWANCE)
        and not memory_failures(
            receipt["last_resources"], aggregate - CONTROL_ALLOWANCE
        )
        and (
            "unit_final_memory" not in receipt
            or not memory_failures(
                receipt["unit_final_memory"], aggregate - CONTROL_ALLOWANCE
            )
        )
        and receipt["post_exit_memory_peak"]["status"] in ("available", "unavailable")
        and (
            receipt["post_exit_memory_peak"]["status"] == "unavailable"
            or receipt["post_exit_memory_peak"]["bytes"]
            <= aggregate - CONTROL_ALLOWANCE
        ),
        "capacity_checkpoint_failed",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("controller", "worker"))
    parser.add_argument("--role", choices=("producer", "consumer"), default="consumer")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "worker":
        worker(args.root, args.base, args.repository, args.sha, args.role)
    else:
        controller(
            args.base.resolve(strict=True),
            args.repository,
            args.sha,
            args.output,
            args.role,
        )


if __name__ == "__main__":
    main()
