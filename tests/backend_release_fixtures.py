"""Synthetic declarations: no installed package or production evidence."""

from dataclasses import asdict, replace
import json

from scripts.backend_release.contracts import (
    CodeEvidence,
    EnvironmentEvidence,
    FileEvidence,
    FixturePaths,
    InterpreterEvidence,
    PackageEvidence,
    PlatformEvidence,
    Release,
    RequestIdentity,
    RUNTIME_FILES,
)
from scripts.backend_release.unit import CANONICAL_POLICY_DIGEST


def environment(root, env_id="legacy"):
    fixtures = FixturePaths(str(root), str(root) + "/legacy/venv")
    return EnvironmentEvidence(
        fixtures,
        env_id,
        fixtures.legacy_env if env_id == "legacy" else fixtures.environment(env_id),
        "legacy" if env_id == "legacy" else "prepared",
        "b" * 64,
        InterpreterEvidence(
            "3.13.14", "cpython", "cp313", str(root) + "/python/bin/python", "c" * 64
        ),
        PlatformEvidence("linux", "x86_64", "glibc-2.39"),
        (PackageEvidence("gunicorn", "23.0.0", "d" * 64),),
    )


def release(root, generation=1, env_id="legacy"):
    return Release(
        CodeEvidence(
            str(generation) * 40,
            tuple(
                FileEvidence(name, "a" * 64, 10, 0o644, "file")
                for name in sorted(RUNTIME_FILES)
            ),
        ),
        environment(root, env_id),
        CANONICAL_POLICY_DIGEST,
        "e" * 64,
        "f" * 64,
        RequestIdentity(f"request-{generation}", 123, generation, generation),
    )


def changed_runtime(value):
    first, *rest = value.code.files
    return replace(
        value, code=replace(value.code, files=(replace(first, sha256="9" * 64), *rest))
    )


def release_record(value):
    result = asdict(value)
    del result["environment"]["fixtures"]
    result["code"]["runtime_digest"] = value.code.runtime_digest
    return json.loads(json.dumps(result))


def wheel_record(root):
    env = environment(root)
    return {
        "requirements_digest": env.requirements_digest,
        "interpreter": asdict(env.interpreter),
        "platform": asdict(env.platform),
        "wheels": [
            {
                "filename": "gunicorn-23.0.0-py3-none-any.whl",
                "name": "gunicorn",
                "version": "23.0.0",
                "size": 1024,
                "sha256": "8" * 64,
            }
        ],
        "offline_proof_digest": None,
    }
