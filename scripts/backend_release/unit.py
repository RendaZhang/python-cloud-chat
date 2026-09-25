"""Render strings from the reviewed policy; never read or install a host unit."""

import hashlib
import shlex

from .contracts import EnvironmentEvidence, digest, require, text

CANONICAL_POLICY_DIGEST = (
    "971a23dd527f7bfa1f928bb9c5c64580099697720fd5d9af1f814015f48b42b2"
)


def render_unit(
    policy: str,
    *,
    source_sha: str,
    environment: EnvironmentEvidence,
    candidate_id: str | None = None,
) -> str:
    require(type(policy) is str and len(policy) <= 16 * 1024, "Invalid unit policy")
    require(
        hashlib.sha256(policy.encode("utf-8")).hexdigest() == CANONICAL_POLICY_DIGEST,
        "Canonical policy changed: separate review required",
    )
    digest(source_sha, 40)
    require(type(environment) is EnvironmentEvidence, "Explicit environment required")
    runtime_name = "cloudchat"
    if candidate_id is not None:
        runtime_name = "cloudchat-preflight-" + text(
            candidate_id, r"[a-z0-9][a-z0-9-]*", 64
        )

    output = []
    for line in policy.splitlines():
        if line.startswith("WorkingDirectory="):
            line = "WorkingDirectory=" + environment.fixtures.code(source_sha)
        elif line.startswith("ExecStart="):
            args = shlex.split(line.removeprefix("ExecStart="))
            args[0] = environment.final_path + "/bin/gunicorn"
            if candidate_id is not None:
                args[args.index("--bind") + 1] = "127.0.0.1:5001"
                args[args.index("--worker-tmp-dir") + 1] = "/run/" + runtime_name
            line = "ExecStart=" + " ".join(args)
        elif candidate_id is not None:
            if line in ("StateDirectory=cloudchat", "StateDirectoryMode=0750"):
                continue
            if line == "Environment=HOME=/var/lib/cloudchat":
                line = "Environment=HOME=/run/" + runtime_name
            elif line == "RuntimeDirectory=cloudchat":
                line = "RuntimeDirectory=" + runtime_name
            elif line == "Restart=always":
                line = "Restart=no\nRuntimeMaxSec=35"
        output.append(line)
    return "\n".join(output) + "\n"
