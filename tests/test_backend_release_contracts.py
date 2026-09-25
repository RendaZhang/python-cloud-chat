from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.backend_release.contracts import (
    ContractError,
    CodeEvidence,
    FixturePaths,
    MAX_RECORD_BYTES,
    MIB,
    PackageEvidence,
    RequestIdentity,
    load_record,
    parse_release,
    parse_wheels,
)
from tests.backend_release_fixtures import (
    environment,
    release,
    release_record,
    wheel_record,
)


class BackendReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = release(self.root)
        self.fixtures = self.release.environment.fixtures

    def test_release_round_trip_and_runtime_digest(self):
        parsed = parse_release(json.dumps(release_record(self.release)), self.fixtures)
        self.assertEqual(parsed, self.release)
        reversed_code = replace(parsed.code, files=tuple(reversed(parsed.code.files)))
        self.assertEqual(reversed_code.runtime_digest, parsed.code.runtime_digest)

    def test_release_identity_canonicalizes_all_unordered_inventories(self):
        package = PackageEvidence("another", "1.0", "0" * 64)
        env = replace(
            self.release.environment,
            packages=self.release.environment.packages + (package,),
        )
        original = replace(self.release, environment=env)
        reordered = replace(
            original,
            code=replace(original.code, files=tuple(reversed(original.code.files))),
            environment=replace(env, packages=tuple(reversed(env.packages))),
        )
        self.assertEqual(original.code.runtime_digest, reordered.code.runtime_digest)
        self.assertEqual(
            original.environment.identity_digest, reordered.environment.identity_digest
        )
        self.assertEqual(original.identity_digest, reordered.identity_digest)

    def test_nonstandard_and_nonfinite_json_numbers_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                load_record('{"nested":{"value":' + value + "}}")

    def test_unknown_and_missing_top_level_keys_rejected(self):
        for key in ("message", "token", "email", "unknown"):
            data = release_record(self.release)
            data[key] = "not-recorded"
            with self.subTest(key=key), self.assertRaises(ContractError):
                parse_release(json.dumps(data), self.fixtures)
        data = release_record(self.release)
        del data["request"]
        with self.assertRaises(ContractError):
            parse_release(json.dumps(data), self.fixtures)

    def test_unknown_nested_keys_rejected(self):
        for keys in (
            ("environment", "interpreter"),
            ("environment", "platform"),
            ("request",),
            ("code",),
        ):
            data = release_record(self.release)
            current = data
            for key in keys:
                current = current[key]
            current["private"] = "not-recorded"
            with self.subTest(keys=keys), self.assertRaises(ContractError):
                parse_release(json.dumps(data), self.fixtures)

    def test_duplicate_json_keys_rejected_at_any_depth(self):
        for value in ('{"x":1,"x":2}', '{"x":{"a":1,"a":2}}'):
            with self.subTest(value=value), self.assertRaises(ContractError):
                load_record(value)

    def test_malformed_nonobject_and_oversized_json_rejected(self):
        for value in (
            "[1]",
            "null",
            "broken",
            '{"x":"' + "a" * MAX_RECORD_BYTES + '"}',
            '{"x":"' + "字" * 24000 + '"}',
        ):
            with self.subTest(length=len(value)), self.assertRaises(ContractError):
                load_record(value)

    def test_strict_numbers_not_bool_float_or_unbounded(self):
        for value in (True, False, 1.0, "1", 0, -1, 2**64):
            with self.subTest(value=value), self.assertRaises(ContractError):
                RequestIdentity("run", value, 1, 1)
        with self.assertRaises(ContractError):
            replace(self.release.code.files[0], size=True)
        with self.assertRaises(ContractError):
            replace(self.release.code.files[0], mode=420.0)

    def test_hash_and_runtime_identity_rejected(self):
        for value in ("A" * 40, "a" * 39, "a" * 41, "../head"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                replace(self.release.code, source_sha=value)
        data = release_record(self.release)
        data["code"]["runtime_digest"] = "0" * 64
        with self.assertRaises(ContractError):
            parse_release(json.dumps(data), self.fixtures)

    def test_fixture_roots_are_explicit_lexical_and_not_live(self):
        for root in (
            "relative",
            "/",
            "/opt/cloudchat",
            "/etc/cloudchat",
            "/var/www",
            "/tmp/a/../b",
            "/tmp//x",
        ):
            with self.subTest(root=root), self.assertRaises(ContractError):
                FixturePaths(root, root + "/legacy/venv")
        with self.assertRaises(ContractError):
            FixturePaths(str(self.root), str(self.root) + "-other/venv")
        self.assertFalse((self.root / "legacy").exists())

    def test_code_path_traversal_private_paths_and_injection_rejected(self):
        for value in (
            "../app.py",
            "/app.py",
            "a//b.py",
            "a/./b.py",
            "app.py\nExecStart=x",
            "app%h.py",
            ".env",
            ".git/config",
            "venv/a.py",
            "instance/users.db",
            "key.pem",
            "x.pyc",
        ):
            with self.subTest(value=value), self.assertRaises(ContractError):
                replace(self.release.code.files[0], path=value)

    def test_special_files_and_unsafe_modes_rejected(self):
        for kind in ("symlink", "hardlink", "directory", "fifo", "device"):
            with self.subTest(kind=kind), self.assertRaises(ContractError):
                replace(self.release.code.files[0], kind=kind)
        for mode in (0o777, 0o4755, 0o664, 0o600):
            with self.subTest(mode=mode), self.assertRaises(ContractError):
                replace(self.release.code.files[0], mode=mode)

    def test_duplicate_missing_and_parent_collision_code(self):
        files = self.release.code.files
        for values in (
            files + (files[0],),
            files[1:],
            files + (replace(files[0], path=files[0].path + "/child"),),
        ):
            with self.subTest(size=len(values)), self.assertRaises(ContractError):
                CodeEvidence("1" * 40, values)

    def test_code_size_and_count_bounds(self):
        with self.assertRaises(ContractError):
            replace(self.release.code.files[0], size=16 * MIB + 1)
        with self.assertRaises(ContractError):
            replace(
                self.release.code,
                files=tuple(replace(f, size=16 * MIB) for f in self.release.code.files),
            )
        with self.assertRaises(ContractError):
            replace(self.release.code, files=self.release.code.files * 80)

    def test_package_inventory_strict_and_unique(self):
        env = self.release.environment
        for values in ((), env.packages * 2, list(env.packages)):
            with self.subTest(kind=type(values).__name__), self.assertRaises(
                ContractError
            ):
                replace(env, packages=values)
        for name in ("Gunicorn", "my_package", "../pkg", "pkg\n"):
            with self.subTest(name=name), self.assertRaises(ContractError):
                PackageEvidence(name, "1.0", "a" * 64)

    def test_fixed_environment_path_cannot_be_moved(self):
        env = environment(self.root, "candidate-1")
        for final_path in (
            str(self.root / "staging/candidate-1"),
            self.fixtures.legacy_env,
            env.final_path + "/..",
        ):
            with self.subTest(path=final_path), self.assertRaises(ContractError):
                replace(env, final_path=final_path)
        with self.assertRaises(ContractError):
            replace(self.release.environment, env_id="copied-legacy")

    def test_interpreter_and_platform_are_bound_but_not_measured(self):
        env = self.release.environment
        for updates in (
            {"version": "3.14.0"},
            {"abi": "cp313t"},
            {"implementation": "pypy"},
        ):
            with self.subTest(updates=updates), self.assertRaises(ContractError):
                replace(env.interpreter, **updates)
        with self.assertRaises(ContractError):
            replace(
                env, interpreter=replace(env.interpreter, base_path="/usr/bin/python3")
            )
        with self.assertRaises(ContractError):
            replace(env.platform, system="darwin")

    def test_wheel_structure_not_a_compatibility_claim(self):
        record = wheel_record(self.root)
        wheels = parse_wheels(json.dumps(record), self.fixtures)
        self.assertIsNone(wheels.offline_proof_digest)
        self.assertEqual(wheels.platform, self.release.environment.platform)
        record["offline_proof_digest"] = "a" * 64
        self.assertEqual(
            parse_wheels(json.dumps(record), self.fixtures).offline_proof_digest,
            "a" * 64,
        )
        self.assertFalse(hasattr(wheels, "compatible"))

    def test_wheels_reject_duplicate_projects_paths_and_unknown_evidence(self):
        base = wheel_record(self.root)
        duplicate = deepcopy(base)
        duplicate["wheels"] *= 2
        unknown = deepcopy(base)
        unknown["wheels"][0]["url"] = "https://example.invalid/private"
        for data in (duplicate, unknown):
            with self.assertRaises(ContractError):
                parse_wheels(json.dumps(data), self.fixtures)
        for filename in (
            "../pkg.whl",
            "/pkg.whl",
            "pkg.tar.gz",
            "x\n.whl",
            ".hidden.whl",
        ):
            data = deepcopy(base)
            data["wheels"][0]["filename"] = filename
            with self.subTest(filename=filename), self.assertRaises(ContractError):
                parse_wheels(json.dumps(data), self.fixtures)

    def test_wheel_byte_and_count_bounds(self):
        data = wheel_record(self.root)
        data["wheels"][0]["size"] = 256 * MIB + 1
        with self.assertRaises(ContractError):
            parse_wheels(json.dumps(data), self.fixtures)
        data["wheels"][0]["size"] = 256 * MIB
        second = dict(data["wheels"][0], name="another", filename="another.whl", size=1)
        data["wheels"].append(second)
        with self.assertRaises(ContractError):
            parse_wheels(json.dumps(data), self.fixtures)

    def test_parsing_and_construction_create_no_files(self):
        parse_release(json.dumps(release_record(self.release)), self.fixtures)
        parse_wheels(json.dumps(wheel_record(self.root)), self.fixtures)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_imports_have_no_write_process_network_or_app_side_effects(self):
        repository = str(Path(__file__).resolve().parents[1])
        script = """
import sys
sys.path.insert(0, sys.argv[1])
sys.dont_write_bytecode = True
def audit(event, args):
    if event in ('os.mkdir', 'os.remove', 'os.rename', 'subprocess.Popen', 'socket.__new__'):
        raise AssertionError(event)
    if event == 'open' and ((isinstance(args[1], str) and any(c in args[1] for c in 'wax+')) or (isinstance(args[2], int) and args[2] & 3)):
        raise AssertionError('write')
sys.addaudithook(audit)
from scripts.backend_release import contracts, decisions, state, unit
assert 'app' not in sys.modules and 'flask' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, repository],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.root.iterdir()), [])
