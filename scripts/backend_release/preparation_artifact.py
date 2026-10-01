"""Bounded same-run wheel transport for the disposable probe, not deployment."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

MIB = 1024 * 1024
ARCHIVE_LIMIT = 128 * MIB  # Archive plus extracted wheels share the 256 MiB slot.
MANIFEST_LIMIT = 65536


class ArtifactError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ArtifactError(code)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_manifest_key")
        result[key] = value
    return result


def read_json(raw):
    require(len(raw) <= MANIFEST_LIMIT, "manifest_bound")

    def reject_constant(_):
        raise ArtifactError("nonfinite_manifest_number")

    return json.loads(
        raw, object_pairs_hook=unique_object, parse_constant=reject_constant
    )


def create_bundle(wheels, manifest):
    raw = json.dumps(manifest, sort_keys=True).encode()
    require(len(raw) <= MANIFEST_LIMIT, "manifest_bound")
    destination = wheels / "bundle.zip"
    files = [wheels / entry["filename"] for entry in manifest["wheels"]]
    require(
        sum(file.stat().st_size for file in files) + len(raw) < ARCHIVE_LIMIT - MIB,
        "bundle_size_bound",
    )
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", raw)
        for file in files:
            archive.write(file, file.name)
    require(destination.stat().st_size <= ARCHIVE_LIMIT, "bundle_size_bound")
    return destination


def safe_members(archive, *, maximum):
    entries = archive.infolist()
    require(0 < len(entries) <= maximum, "archive_member_count")
    names = set()
    total = 0
    for entry in entries:
        mode = entry.external_attr >> 16
        require(
            re.fullmatch(r"[A-Za-z0-9_.+!-]{1,200}", entry.filename)
            and entry.filename not in (".", "..")
            and entry.filename not in names
            and not entry.is_dir()
            and stat.S_IFMT(mode) in (0, stat.S_IFREG)
            and not entry.flag_bits & 1,
            "unsafe_archive_member",
        )
        names.add(entry.filename)
        total += entry.file_size
        require(
            0 < entry.file_size <= ARCHIVE_LIMIT and total <= ARCHIVE_LIMIT,
            "expanded_archive_bound",
        )
    return entries


def extract_file(archive, entry, destination):
    # Do not delegate paths, symlink semantics or overwrite policy to extractall.
    with archive.open(entry) as source, destination.open("xb") as output:
        written = 0
        while chunk := source.read(65536):
            written += len(chunk)
            require(written <= entry.file_size, "expanded_archive_bound")
            output.write(chunk)
        require(written == entry.file_size, "truncated_archive_member")


def unpack_outer(outer, wheels, expected_digest):
    require(digest(outer) == expected_digest, "artifact_digest_mismatch")
    with zipfile.ZipFile(outer) as archive:
        entries = safe_members(archive, maximum=1)
        require(entries[0].filename == "bundle.zip", "unexpected_outer_member")
        extract_file(archive, entries[0], wheels / "bundle.zip")
    outer.unlink()  # Only our just-verified ingress file, before inner expansion.


def unpack_bundle(wheels, *, source_sha, requirements_sha, run_id, attempt, base):
    bundle = wheels / "bundle.zip"
    with zipfile.ZipFile(bundle) as archive:
        entries = safe_members(archive, maximum=74)
        by_name = {entry.filename: entry for entry in entries}
        require("manifest.json" in by_name, "manifest_missing")
        require(by_name["manifest.json"].file_size <= MANIFEST_LIMIT, "manifest_bound")
        manifest = read_json(archive.read(by_name["manifest.json"]))
        require(isinstance(manifest, dict), "manifest_object")
        require(
            set(manifest)
            == {
                "schema",
                "source_sha",
                "requirements_sha256",
                "run_id",
                "attempt",
                "producer",
                "wheels",
            },
            "manifest_fields",
        )
        require(
            type(manifest["schema"]) is int
            and manifest["schema"] == 1
            and manifest["source_sha"] == source_sha
            and manifest["requirements_sha256"] == requirements_sha
            and manifest["run_id"] == run_id
            and manifest["attempt"] == attempt,
            "artifact_identity_mismatch",
        )
        producer = manifest["producer"]
        # Provenance paths/digests are recorded, not equated across independent runners.
        for key in (
            "version",
            "implementation",
            "free_threaded",
            "soabi",
            "system",
            "architecture",
            "libc",
            "seed_version",
            "seed_sha256",
        ):
            require(producer[key] == base[key], "artifact_platform_mismatch")
        require(isinstance(producer.get("pip_version"), str), "producer_tool_missing")
        files = manifest["wheels"]
        require(isinstance(files, list) and len(files) == 73, "manifest_wheel_count")
        require(
            all(
                isinstance(entry, dict)
                and set(entry) == {"filename", "name", "version", "size", "sha256"}
                for entry in files
            ),
            "manifest_wheel_fields",
        )
        names = [entry["filename"] for entry in files]
        require(
            len(set(names)) == 73 and set(by_name) == set(names) | {"manifest.json"},
            "artifact_inventory_mismatch",
        )
        for declared in files:
            entry = by_name[declared["filename"]]
            require(
                entry.filename.endswith(".whl")
                and type(declared["size"]) is int
                and entry.file_size == declared["size"]
                and re.fullmatch(r"[0-9a-f]{64}", declared["sha256"]),
                "artifact_wheel_declaration",
            )
            destination = wheels / entry.filename
            extract_file(archive, entry, destination)
            require(digest(destination) == declared["sha256"], "wheel_digest_mismatch")
    manifest_digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    bundle.unlink()
    return manifest, manifest_digest


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return urllib.request.Request(url, headers=headers)


def receive(wheels, *, repository, artifact_id, expected_digest, run_id, source_sha):
    """All TLS, bytes, hashes and extraction run in the consumer's measured service."""
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository),
        "repository_identity",
    )
    require(
        artifact_id.isdecimal() and re.fullmatch(r"[0-9a-f]{64}", expected_digest),
        "artifact_identity",
    )
    token = os.environ.pop("GH_ARTIFACT_TOKEN", "")
    require(bool(token), "ephemeral_token_missing")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    endpoint = (
        f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}"
    )
    try:
        # The command-level 120s process deadline also bounds slow/trickling responses.
        with opener.open(request(endpoint, token), timeout=20) as response:
            metadata = read_json(response.read(MANIFEST_LIMIT + 1))
        require(
            metadata["id"] == int(artifact_id)
            and not metadata["expired"]
            and metadata["workflow_run"]["id"] == int(run_id)
            and metadata["workflow_run"]["head_sha"] == source_sha
            and metadata["digest"] == "sha256:" + expected_digest
            and 0 < metadata["size_in_bytes"] <= ARCHIVE_LIMIT,
            "remote_artifact_identity",
        )
        try:
            opener.open(request(endpoint + "/zip", token), timeout=20)
            raise ArtifactError("artifact_redirect_missing")
        except urllib.error.HTTPError as response:
            require(response.code == 302, "artifact_redirect_status")
            location = response.headers["Location"]
            response.close()
        parsed = urllib.parse.urlsplit(location)
        require(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and (
                parsed.hostname.endswith(".blob.core.windows.net")
                or parsed.hostname.endswith(".actions.githubusercontent.com")
            ),
            "artifact_redirect_host",
        )
        token = None  # Never forward Authorization to the artifact storage origin.
        destination = wheels / "ingress.zip"
        started, received = time.monotonic(), 0
        with opener.open(request(location), timeout=20) as source, destination.open(
            "xb"
        ) as output:
            while chunk := source.read(65536):
                received += len(chunk)
                require(
                    received <= ARCHIVE_LIMIT and time.monotonic() - started < 120,
                    "ingress_bound",
                )
                output.write(chunk)
        require(received == metadata["size_in_bytes"], "ingress_size_mismatch")
        unpack_outer(destination, wheels, expected_digest)
    except ArtifactError:
        raise
    except Exception:
        # URLs, authorization, server response bodies and signed query strings stay private.
        raise ArtifactError("artifact_receive_failed") from None


if __name__ == "__main__":
    import sys

    try:
        receive(
            Path(sys.argv[1]),
            repository=os.environ["ARTIFACT_REPOSITORY"],
            artifact_id=os.environ["ARTIFACT_ID"],
            expected_digest=os.environ["ARTIFACT_DIGEST"],
            run_id=os.environ["GITHUB_RUN_ID"],
            source_sha=os.environ["GITHUB_SHA"],
        )
    except ArtifactError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("artifact_ingress_refused") from None
