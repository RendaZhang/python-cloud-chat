"""Disposable Linux CI capacity checkpoint, not a release builder or host adapter."""

import argparse
import hashlib
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
DISK_LIMITS = {
    "envs": 384 * MIB,
    "wheels": 256 * MIB,
    "workspace": 128 * MIB,
    "cache": 64 * MIB,
    "receipts": 64 * MIB,
}
TOTAL_LIMIT = 1280 * MIB
ROOT_PREFIX = "backend-offline-proof-"
STAGES = (
    "tracked_inputs",
    "interpreter",
    "binary_download",
    "wheel_metadata",
    "network_isolation",
    "final_path_seed",
    "offline_install",
    "offline_verification",
)
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


def command(args, *, root, timeout, offline=False, capture=False):
    if offline:
        args = ["/usr/bin/unshare", "--net", "--", *args]
    log = root / "workspace/command.log"
    with log.open("wb") as output:
        proc = subprocess.Popen(
            args,
            cwd=root,
            env=clean_environment(root),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
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
        require(log.stat().st_size <= MIB, "child_output_bound")
        if code:
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
import json, pathlib, socket
interfaces = sorted(p.name for p in pathlib.Path('/sys/class/net').iterdir())
assert interfaces == ['lo'], interfaces
for address in ('192.0.2.1', '1.1.1.1'):
    with socket.socket() as sock:
        sock.settimeout(1)
        assert sock.connect_ex((address, 443)) != 0
print(json.dumps({'interfaces': interfaces, 'external_connect': 'blocked'}))
"""

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
print(json.dumps({'packages': names, 'native_imports': list(modules),
 'prefix': sys.prefix, 'base_executable': str(pathlib.Path(sys._base_executable).resolve())}))
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


def memory_failures(memory):
    failures = set()
    if memory["memory.peak"] > MEMORY_LIMIT or memory["memory.current"] > MEMORY_LIMIT:
        failures.add("measured_memory_budget_exceeded")
    if memory["memory.swap.peak"] != 0:
        failures.add("measured_swap_budget_exceeded")
    if any(
        memory["memory.events"].get(key, 0)
        for key in ("oom", "oom_kill", "oom_group_kill")
    ):
        failures.add("memory_oom_event")
    return failures


class Meter:
    def __init__(self, root, cgroup):
        self.root, self.cgroup = root, cgroup
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
            usage = {name: allocated_tree(self.root / name) for name in DISK_LIMITS}
            usage["total"] = allocated_tree(self.root)
            memory = memory_snapshot(self.cgroup)
            now = time.monotonic()
            self.max_sample_gap_seconds = max(
                self.max_sample_gap_seconds, now - self.previous_sample
            )
            self.previous_sample = now
            self.samples += 1
            self.update_high_water(self.high_water, usage)
            self.resource_failures.update(memory_failures(memory))
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
        for name, limit in {**DISK_LIMITS, "total": TOTAL_LIMIT}.items():
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


def worker(root, base, repository, target_sha):
    require(
        sys.platform == "linux" and os.geteuid() == 0, "disposable_linux_root_required"
    )
    require(
        root.parent == Path("/tmp") and root.name.startswith(ROOT_PREFIX),
        "fixture_root",
    )
    require(
        root == root.resolve() and stat.S_IMODE(root.stat().st_mode) == 0o700,
        "private_root",
    )
    relative = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
    require(ROOT_PREFIX in relative, "owned_cgroup_required")
    cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
    require(
        int((cgroup / "memory.max").read_text()) == MEMORY_LIMIT, "memory_limit_missing"
    )
    require(int((cgroup / "memory.swap.max").read_text()) == 0, "swap_limit_missing")
    receipt = {"scope": "disposable-linux-capacity-checkpoint", "status": "running"}
    meter = Meter(root, cgroup)
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
        shutil.copyfile(__file__, root / "workspace/probe.py")
        enter_stage(root, receipt, meter, "interpreter")
        receipt["base"] = verify_base(base, root)
        requirements = root / "workspace/requirements.txt"
        expected = pins(requirements.read_bytes())
        receipt["requirements_sha256"] = sha256(requirements)
        receipt["pin_count"] = len(expected)
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
        hashed = diagnose_wheels(root, expected, receipt, meter)
        locked = root / "workspace/install.txt"
        locked.write_text(hashed)
        enter_stage(root, receipt, meter, "network_isolation")
        receipt["network"] = json.loads(
            command(
                [str(base), "-I", "-B", "-c", NETWORK_PROBE],
                root=root,
                timeout=10,
                offline=True,
                capture=True,
            )
        )
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
            and installed["base_executable"] == str(base),
            "environment_identity_mismatch",
        )
        receipt["installed"] = installed
        require(sha256(base) == receipt["base"]["binary_sha256"], "base_binary_changed")
        meter.check_limits()
        receipt["status"] = "capacity_checkpoint_passed_not_release_ready"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["failure"] = (
            str(error) if isinstance(error, ProofError) else type(error).__name__
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
            final_failures = memory_failures(latest)
            if final_failures:
                receipt["status"] = "failed"
                receipt["resource_failure"] = ",".join(sorted(final_failures))
            receipt["disk_measurement"] = (
                "nominal 100ms samples plus final check; actual sample gaps recorded; not disk quotas"
            )
            write_receipt(root, receipt)
            require(not final_failures, ",".join(sorted(final_failures)))


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


def controller(base, repository, target_sha, output):
    require(os.environ.get("GITHUB_ACTIONS") == "true", "github_runner_only")
    require(
        sys.platform == "linux" and os.geteuid() == 0, "disposable_linux_root_required"
    )
    require(
        'VERSION_ID="24.04"' in Path("/etc/os-release").read_text(),
        "ubuntu_24_required",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", target_sha), "exact_sha_required")
    root = Path(tempfile.mkdtemp(prefix=ROOT_PREFIX, dir="/tmp"))
    unit = root.name + ".service"
    receipt = {
        "source_sha": target_sha,
        "unit": unit,
        "memory_limit": MEMORY_LIMIT,
        "swap_limit": 0,
        "disk_limits": DISK_LIMITS,
        "total_disk_limit": TOTAL_LIMIT,
        "protected_environment_count": 0,
        "not_proved": [
            "immutable_release_publication",
            "protected_environment_reuse",
            "production_host_capacity",
        ],
        "production_identity": False,
        "cleanup": "pending",
    }
    proc = None
    try:
        for name in DISK_LIMITS:
            (root / name).mkdir(mode=0o700)
        for name in ("home", "tmp"):
            (root / "workspace" / name).mkdir(mode=0o700)
        args = [
            "systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--unit=" + unit,
            "--property=MemoryAccounting=yes",
            "--property=MemoryMax=" + str(MEMORY_LIMIT),
            "--property=MemorySwapMax=0",
            "--property=TasksMax=64",
            "--property=RuntimeMaxSec=650",
            "--property=TimeoutStopSec=10",
            "--property=KillMode=control-group",
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
        ]
        proc = subprocess.Popen(args, start_new_session=True)
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
            if receipt["systemd"].get("LoadState") != "not-found":
                subprocess.run(["systemctl", "stop", unit], timeout=15, check=True)
            remaining = unit_properties(unit)
            require(remaining.get("MainPID") == "0", "owned_processes_not_reaped")
            group = receipt["systemd"].get("ControlGroup", "")
            require(
                not group or (group.startswith("/") and ROOT_PREFIX in group),
                "unexpected_owned_cgroup",
            )
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
        receipt["outside_ci_supervisor"] = {
            "controller_peak_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            * 1024,
            "serial_launcher_control_children_max_rss_bytes": resource.getrusage(
                resource.RUSAGE_CHILDREN
            ).ru_maxrss
            * 1024,
            "measurement": "Linux getrusage high-water, separate from preparation cgroup; not an aggregate hard limit",
        }
        if receipt["cleanup"] == "owned_unit_stopped_mainpid_zero_cgroup_empty":
            try:
                shutil.rmtree(root)
                receipt["cleanup"] += "_fixture_removed"
            except OSError:
                receipt["cleanup"] = "failed_fixture_preserved"
        output.mkdir(mode=0o755, parents=True, exist_ok=True)
        raw_receipt = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        require(len(raw_receipt.encode()) <= 65536, "controller_receipt_bound")
        (output / "capacity.json").write_text(raw_receipt)
        print(raw_receipt, flush=True)
    require(
        receipt.get("unit_returncode") == 0
        and "controller_failure" not in receipt
        and receipt["worker"].get("status")
        == "capacity_checkpoint_passed_not_release_ready"
        and receipt["cleanup"]
        == "owned_unit_stopped_mainpid_zero_cgroup_empty_fixture_removed",
        "capacity_checkpoint_failed",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("controller", "worker"))
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "worker":
        worker(args.root, args.base, args.repository, args.sha)
    else:
        controller(
            args.base.resolve(strict=True), args.repository, args.sha, args.output
        )


if __name__ == "__main__":
    main()
