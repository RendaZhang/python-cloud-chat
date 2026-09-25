"""Bounded declarations, not verification of files, installed packages, or hosts."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import PurePosixPath
import re

MIB = 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024
RUNTIME_FILES = frozenset(
    {
        "app.py",
        "app_auth.py",
        "chat_guide_prompt.py",
        "db.py",
        "mailer.py",
        "models.py",
        "security_policy.py",
    }
)


class ContractError(ValueError):
    """Invalid or unsupported release declaration; never echo its raw value."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def text(value: str, pattern: str, maximum: int = 128) -> str:
    require(
        type(value) is str
        and 0 < len(value) <= maximum
        and re.fullmatch(pattern, value, flags=re.ASCII) is not None,
        "Invalid bounded text",
    )
    return value


def digest(value: str, length: int = 64) -> str:
    return text(value, rf"[0-9a-f]{{{length}}}", length)


def integer(value: int, minimum: int = 1, maximum: int = 2**63 - 1) -> int:
    require(type(value) is int and minimum <= value <= maximum, "Invalid integer")
    return value


def boolean(value: bool) -> bool:
    require(type(value) is bool, "Invalid boolean")
    return value


def fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def path(value: str, *, absolute: bool) -> str:
    text(value, r"[A-Za-z0-9_./-]+", 240)
    parsed = PurePosixPath(value)
    require(
        parsed.is_absolute() == absolute
        and str(parsed) == value
        and value not in ("/", ".")
        and ".." not in parsed.parts
        and "//" not in value,
        "Invalid lexical path",
    )
    return value


@dataclass(frozen=True)
class FixturePaths:
    root: str
    legacy_env: str

    def __post_init__(self):
        path(self.root, absolute=True)
        require(
            not any(
                self.root == prefix or self.root.startswith(prefix + "/")
                for prefix in ("/opt", "/etc", "/usr", "/var/www")
            ),
            "Live roots are outside this pure fixture contract",
        )
        self.contains(self.legacy_env)
        require(
            not self.legacy_env.startswith(self.root + "/envs/"),
            "Legacy environment must remain distinct",
        )

    def contains(self, value: str) -> str:
        path(value, absolute=True)
        require(value.startswith(self.root + "/"), "Path escapes fixture root")
        return value

    def code(self, sha: str) -> str:
        return self.root + "/code/" + digest(sha, 40)

    def environment(self, env_id: str) -> str:
        return self.root + "/envs/" + text(env_id, r"[a-z0-9][a-z0-9-]*", 80)


@dataclass(frozen=True)
class FileEvidence:
    path: str
    sha256: str
    size: int
    mode: int
    kind: str

    def __post_init__(self):
        path(self.path, absolute=False)
        parts = PurePosixPath(self.path).parts
        require(
            not any(part.startswith(".") for part in parts)
            and not set(parts) & {"venv", "instance", "secrets", "logs", "__pycache__"}
            and not self.path.endswith((".pem", ".key", ".env", ".pyc")),
            "Private or runtime-state path is not code evidence",
        )
        digest(self.sha256)
        integer(self.size, 0, 16 * MIB)
        integer(self.mode, 0, 0o7777)
        require(self.kind == "file", "Only regular file evidence is allowed")
        require(self.mode in (0o444, 0o644, 0o555, 0o755), "Unsafe file mode")


@dataclass(frozen=True)
class CodeEvidence:
    source_sha: str
    files: tuple[FileEvidence, ...]

    def __post_init__(self):
        digest(self.source_sha, 40)
        require(type(self.files) is tuple, "File inventory must be immutable")
        require(1 <= len(self.files) <= 512, "File inventory bound exceeded")
        require(
            all(type(f) is FileEvidence for f in self.files), "Invalid file evidence"
        )
        names = [f.path for f in self.files]
        require(len(set(names)) == len(names), "Duplicate file path")
        require(
            not any(
                str(parent) in names
                for name in names
                for parent in PurePosixPath(name).parents
            ),
            "File path is also used as a directory",
        )
        require(RUNTIME_FILES <= set(names), "Missing runtime module")
        require(sum(f.size for f in self.files) <= 48 * MIB, "Code byte bound exceeded")

    @property
    def runtime_digest(self) -> str:
        return fingerprint(
            [asdict(f) for f in sorted(self.files, key=lambda f: f.path)]
        )


@dataclass(frozen=True)
class InterpreterEvidence:
    version: str
    implementation: str
    abi: str
    base_path: str
    binary_digest: str

    def __post_init__(self):
        require(
            (self.version, self.implementation, self.abi)
            == ("3.13.14", "cpython", "cp313"),
            "Interpreter differs from the reviewed runtime",
        )
        path(self.base_path, absolute=True)
        digest(self.binary_digest)


@dataclass(frozen=True)
class PlatformEvidence:
    system: str
    architecture: str
    libc: str

    def __post_init__(self):
        require(self.system == "linux", "Expected declared Linux platform")
        require(self.architecture in ("x86_64", "aarch64"), "Unsupported architecture")
        text(self.libc, r"glibc-[0-9]+\.[0-9]+", 32)


@dataclass(frozen=True)
class PackageEvidence:
    name: str
    version: str
    inventory_digest: str

    def __post_init__(self):
        text(self.name, r"[a-z0-9]+(?:-[a-z0-9]+)*", 80)
        text(self.version, r"[A-Za-z0-9][A-Za-z0-9.+!-]*", 64)
        digest(self.inventory_digest)


@dataclass(frozen=True)
class EnvironmentEvidence:
    fixtures: FixturePaths
    env_id: str
    final_path: str
    origin: str
    requirements_digest: str
    interpreter: InterpreterEvidence
    platform: PlatformEvidence
    packages: tuple[PackageEvidence, ...]

    def __post_init__(self):
        require(type(self.fixtures) is FixturePaths, "Explicit fixture roots required")
        text(self.env_id, r"[a-z0-9][a-z0-9-]*", 80)
        require(self.origin in ("legacy", "prepared"), "Unknown environment origin")
        expected = (
            self.fixtures.legacy_env
            if self.origin == "legacy"
            else self.fixtures.environment(self.env_id)
        )
        require(self.final_path == expected, "Environment cannot be moved or renamed")
        require(self.origin != "legacy" or self.env_id == "legacy", "Invalid legacy ID")
        digest(self.requirements_digest)
        require(type(self.interpreter) is InterpreterEvidence, "Invalid interpreter")
        self.fixtures.contains(self.interpreter.base_path)
        require(type(self.platform) is PlatformEvidence, "Invalid platform")
        require(type(self.packages) is tuple, "Package inventory must be immutable")
        require(1 <= len(self.packages) <= 256, "Package inventory bound exceeded")
        require(
            all(type(p) is PackageEvidence for p in self.packages), "Invalid package"
        )
        require(
            len({p.name for p in self.packages}) == len(self.packages),
            "Duplicate normalized package",
        )

    @property
    def identity_digest(self) -> str:
        value = asdict(self)
        value["packages"] = [
            asdict(p) for p in sorted(self.packages, key=lambda p: p.name)
        ]
        return fingerprint(value)


@dataclass(frozen=True)
class RequestIdentity:
    request_id: str
    run_id: int
    attempt: int
    generation: int

    def __post_init__(self):
        text(self.request_id, r"[a-z0-9][a-z0-9-]*", 80)
        for value in (self.run_id, self.attempt, self.generation):
            integer(value)


@dataclass(frozen=True)
class Release:
    code: CodeEvidence
    environment: EnvironmentEvidence
    policy_digest: str
    unit_digest: str
    helper_digest: str
    request: RequestIdentity

    def __post_init__(self):
        require(type(self.code) is CodeEvidence, "Invalid code declaration")
        require(type(self.environment) is EnvironmentEvidence, "Invalid environment")
        require(type(self.request) is RequestIdentity, "Invalid request identity")
        for value in (self.policy_digest, self.unit_digest, self.helper_digest):
            digest(value)

    @property
    def identity_digest(self) -> str:
        return fingerprint(
            {
                "source_sha": self.code.source_sha,
                "runtime_digest": self.code.runtime_digest,
                "environment_digest": self.environment.identity_digest,
                "policy_digest": self.policy_digest,
                "unit_digest": self.unit_digest,
                "helper_digest": self.helper_digest,
                "request": asdict(self.request),
            }
        )


def _fields(value, keys):
    require(
        type(value) is dict and set(value) == set(keys.split()), "Unknown/missing keys"
    )
    return value


def _objects(value, limit=512):
    require(type(value) is list and 1 <= len(value) <= limit, "Invalid bounded list")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ContractError("Non-standard JSON constant")


def _finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "Non-finite JSON number")
    return parsed


def load_record(raw: str) -> dict:
    require(type(raw) is str, "Expected JSON text")
    try:
        require(
            len(raw.encode("utf-8")) <= MAX_RECORD_BYTES, "Record byte bound exceeded"
        )
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
            parse_float=_finite_float,
        )
    except (ValueError, RecursionError, UnicodeError) as error:
        raise ContractError("Invalid bounded JSON record") from error
    require(type(value) is dict, "Expected JSON object")
    return value


def _interpreter(value):
    return InterpreterEvidence(
        **_fields(value, "version implementation abi base_path binary_digest")
    )


def _platform(value):
    return PlatformEvidence(**_fields(value, "system architecture libc"))


def parse_environment(value: dict, fixtures: FixturePaths) -> EnvironmentEvidence:
    _fields(
        value,
        "env_id final_path origin requirements_digest interpreter platform packages",
    )
    return EnvironmentEvidence(
        fixtures,
        value["env_id"],
        value["final_path"],
        value["origin"],
        value["requirements_digest"],
        _interpreter(value["interpreter"]),
        _platform(value["platform"]),
        tuple(
            PackageEvidence(**_fields(p, "name version inventory_digest"))
            for p in _objects(value["packages"], 256)
        ),
    )


def parse_release(raw: str, fixtures: FixturePaths) -> Release:
    value = _fields(
        load_record(raw),
        "code environment policy_digest unit_digest helper_digest request",
    )
    code = _fields(value["code"], "source_sha runtime_digest files")
    evidence = CodeEvidence(
        code["source_sha"],
        tuple(
            FileEvidence(**_fields(f, "path sha256 size mode kind"))
            for f in _objects(code["files"])
        ),
    )
    require(
        code["runtime_digest"] == evidence.runtime_digest, "Runtime digest mismatch"
    )
    return Release(
        evidence,
        parse_environment(value["environment"], fixtures),
        value["policy_digest"],
        value["unit_digest"],
        value["helper_digest"],
        RequestIdentity(
            **_fields(value["request"], "request_id run_id attempt generation")
        ),
    )


@dataclass(frozen=True)
class WheelEvidence:
    filename: str
    name: str
    version: str
    size: int
    sha256: str

    def __post_init__(self):
        text(self.filename, r"[A-Za-z0-9_.+-]+\.whl", 200)
        require(not self.filename.startswith("."), "Invalid wheel filename")
        PackageEvidence(self.name, self.version, self.sha256)
        integer(self.size, 1, 256 * MIB)


@dataclass(frozen=True)
class WheelSet:
    requirements_digest: str
    interpreter: InterpreterEvidence
    platform: PlatformEvidence
    wheels: tuple[WheelEvidence, ...]
    offline_proof_digest: str | None

    def __post_init__(self):
        digest(self.requirements_digest)
        require(type(self.interpreter) is InterpreterEvidence, "Invalid interpreter")
        require(type(self.platform) is PlatformEvidence, "Invalid platform")
        require(type(self.wheels) is tuple, "Wheel inventory must be immutable")
        require(1 <= len(self.wheels) <= 256, "Wheel count bound exceeded")
        require(all(type(w) is WheelEvidence for w in self.wheels), "Invalid wheel")
        for key in ("filename", "name"):
            require(
                len({getattr(w, key) for w in self.wheels}) == len(self.wheels),
                "Duplicate wheel filename or project",
            )
        require(
            sum(w.size for w in self.wheels) <= 256 * MIB, "Wheel byte bound exceeded"
        )
        if self.offline_proof_digest is not None:
            digest(self.offline_proof_digest)


def parse_wheels(raw: str, fixtures: FixturePaths) -> WheelSet:
    require(type(fixtures) is FixturePaths, "Explicit fixture roots required")
    value = _fields(
        load_record(raw),
        "requirements_digest interpreter platform wheels offline_proof_digest",
    )
    interpreter = _interpreter(value["interpreter"])
    fixtures.contains(interpreter.base_path)
    return WheelSet(
        value["requirements_digest"],
        interpreter,
        _platform(value["platform"]),
        tuple(
            WheelEvidence(**_fields(w, "filename name version size sha256"))
            for w in _objects(value["wheels"], 256)
        ),
        value["offline_proof_digest"],
    )
