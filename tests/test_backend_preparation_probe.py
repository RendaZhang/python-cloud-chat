"""Portable stdlib tests only; real installs are confined to the isolated CI job."""

import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import stat
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
import urllib.error
import zipfile

from scripts.backend_release import preparation_probe as proof

REPOSITORY = Path(__file__).resolve().parents[1]


class PreparationCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in proof.DISK_LIMITS:
            (self.root / name).mkdir(mode=0o700)
        for name in ("home", "tmp"):
            (self.root / "workspace" / name).mkdir()
        self.set_memory()

    def set_memory(self, *, current=1024, peak=2048, swap=0, events=None):
        values = {
            "memory.current": str(current),
            "memory.peak": str(peak),
            "memory.swap.peak": str(swap),
            "memory.events": events or "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n",
            "memory.stat": "file 512\nunknown_future_key 77\nkernel 256\nanon 128\nslab 64\npgscan 3\npgsteal 2\n",
        }
        for name, value in values.items():
            (self.root / name).write_text(value)

    def wheel(
        self,
        filename="example-1.0-py3-none-any.whl",
        name="example",
        version="1.0",
        member="example-1.0.dist-info/METADATA",
    ):
        destination = self.root / "wheels" / filename
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(
                member,
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
            )
        return destination

    def test_reviewed_requirements_are_73_exact_unique_pins(self):
        result = proof.pins((REPOSITORY / "requirements.txt").read_bytes())
        self.assertEqual(len(result), 73)
        self.assertEqual(result["gevent"], "25.5.1")

    def test_requirement_injections_duplicates_and_changed_count_refused(self):
        original = (REPOSITORY / "requirements.txt").read_bytes()
        for raw in (
            b"",
            original + b"--index-url=https://example.invalid\n",
            original + b"Flask==3.1.3\n",
            original.replace(b"Flask==", b"Flask>="),
            original.replace(b"Flask==3.1.3", b"Flask==3.1.3; os_name=='posix'"),
        ):
            with self.subTest(raw_length=len(raw)), self.assertRaises(proof.ProofError):
                proof.pins(raw)

    def test_controlled_environment_has_no_ambient_proxy_or_pythonpath(self):
        with patch.dict(
            os.environ,
            {
                "PYTHONPATH": "/private",
                "HTTPS_PROXY": "private",
                "PIP_INDEX_URL": "private",
            },
        ):
            env = proof.clean_environment(self.root)
        self.assertEqual(
            set(env),
            {
                "PATH",
                "HOME",
                "TMPDIR",
                "XDG_CACHE_HOME",
                "PIP_CONFIG_FILE",
                "PYTHONDONTWRITEBYTECODE",
                "LANG",
                "LC_ALL",
            },
        )
        self.assertEqual(env["PIP_CONFIG_FILE"], "/dev/null")
        self.assertTrue(env["HOME"].startswith(str(self.root)))

    def test_allocated_accounting_counts_hardlinks_once_and_not_symlink_target(self):
        before = proof.allocated_tree(self.root)
        file = self.root / "workspace/file"
        file.write_bytes(b"x" * 8192)
        os.link(file, self.root / "workspace/alias")
        (self.root / "workspace/outside").symlink_to(
            REPOSITORY, target_is_directory=True
        )
        after = proof.allocated_tree(self.root)
        self.assertEqual(after["files"], before["files"] + 1)
        self.assertEqual(after["inodes"], before["inodes"] + 2)
        self.assertGreaterEqual(after["allocated_bytes"], 8192)

    def test_wheel_hashes_bind_actual_file_bytes(self):
        wheel = self.wheel()
        manifest, locked = proof.hashed_requirements(
            self.root / "wheels", {"example": "1.0"}
        )
        self.assertEqual(manifest[0]["sha256"], proof.sha256(wheel))
        self.assertEqual(
            locked, "example==1.0 --hash=sha256:" + proof.sha256(wheel) + "\n"
        )

    def test_missing_or_unexpected_wheel_refused(self):
        for expected in ({"example": "1.0"},):
            with self.assertRaises(proof.ProofError):
                proof.hashed_requirements(self.root / "wheels", expected)
        self.wheel()
        with self.assertRaises(proof.ProofError):
            proof.hashed_requirements(self.root / "wheels", {"different": "1.0"})

    def test_duplicate_normalized_wheel_project_refused(self):
        self.wheel(
            "my_example-1.0-py3-none-any.whl",
            name="my_example",
            member="my_example-1.0.dist-info/METADATA",
        )
        self.wheel(
            "my.example-1.0-py2-none-any.whl",
            name="my-example",
            member="my.example-1.0.dist-info/METADATA",
        )
        with self.assertRaisesRegex(proof.ProofError, "duplicate_wheel_project"):
            proof.hashed_requirements(self.root / "wheels", {"my-example": "1.0"})

    def test_wrong_wheel_version_refused(self):
        self.wheel(version="9.0")
        with self.assertRaises(proof.ProofError):
            proof.hashed_requirements(self.root / "wheels", {"example": "1.0"})

    def test_wheel_symlink_and_hardlink_refused(self):
        wheel = self.wheel()
        link = self.root / "wheels/alias.whl"
        link.symlink_to(wheel)
        with self.assertRaises(proof.ProofError):
            proof.hashed_requirements(self.root / "wheels", {"example": "1.0"})
        link.unlink()
        os.link(wheel, link)
        with self.assertRaises(proof.ProofError):
            proof.hashed_requirements(self.root / "wheels", {"example": "1.0"})

    def test_metadata_ambiguity_refused(self):
        wheel = self.wheel()
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr(
                "other.dist-info/METADATA", "Name: example\nVersion: 1.0\n"
            )
        with self.assertRaises(proof.ProofError):
            proof.hashed_requirements(self.root / "wheels", {"example": "1.0"})

    def test_root_metadata_with_vendored_metadata_binds_only_root(self):
        wheel = self.wheel()
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr(
                "example/_vendor/vendor-2.0.dist-info/METADATA",
                "Name: vendor\nVersion: 2.0\n",
            )
        diagnostics = {}
        manifest, _ = proof.hashed_requirements(
            self.root / "wheels", {"example": "1.0"}, diagnostics
        )
        self.assertEqual(manifest[0]["name"], "example")
        self.assertEqual(diagnostics["wheels_checked"], 1)
        detail = diagnostics["nested_archives"][0]
        self.assertEqual(detail["metadata_member_count"], 2)
        self.assertEqual(detail["root_metadata_count"], 1)
        self.assertEqual(detail["nested_metadata_count"], 1)
        self.assertEqual(detail["filename"], wheel.name)
        self.assertEqual(detail["root_members"], ["example-1.0.dist-info/METADATA"])

    def test_nested_only_metadata_is_not_a_root_distribution(self):
        self.wheel(member="example/_vendor/example-1.0.dist-info/METADATA")
        diagnostics = {}
        with self.assertRaisesRegex(proof.ProofError, "wheel_metadata"):
            proof.hashed_requirements(
                self.root / "wheels", {"example": "1.0"}, diagnostics
            )
        self.assertEqual(diagnostics["last_archive"]["root_metadata_count"], 0)

    def test_duplicate_root_zip_entry_is_refused(self):
        wheel = self.wheel()
        with zipfile.ZipFile(wheel, "a") as archive, self.assertWarns(UserWarning):
            archive.writestr(
                "example-1.0.dist-info/METADATA", "Name: example\nVersion: 1.0\n"
            )
        with self.assertRaisesRegex(proof.ProofError, "wheel_metadata"):
            proof.hashed_requirements(self.root / "wheels", {"example": "1.0"})

    def test_filename_directory_and_header_identity_must_match(self):
        for member, name, version in (
            ("other-1.0.dist-info/METADATA", "example", "1.0"),
            ("example-2.0.dist-info/METADATA", "example", "1.0"),
            ("example-1.0.dist-info/METADATA", "other", "1.0"),
            ("example-1.0.dist-info/METADATA", "example", "2.0"),
            ("../example-1.0.dist-info/METADATA", "example", "1.0"),
        ):
            with self.subTest(member=member, name=name, version=version):
                self.wheel(member=member, name=name, version=version)
                with self.assertRaises(proof.ProofError):
                    proof.hashed_requirements(self.root / "wheels", {name: version})

    def test_metadata_missing_duplicate_headers_and_size_limit_refused(self):
        for raw, code in (
            ("Version: 1.0\n", "wheel_metadata_headers"),
            ("Name: example\nName: example\nVersion: 1.0\n", "wheel_metadata_headers"),
            ("Name: example\nVersion: 1.0\nVersion: 1.0\n", "wheel_metadata_headers"),
            ("x" * (proof.MIB + 1), "wheel_metadata_size"),
        ):
            with self.subTest(code=code):
                with zipfile.ZipFile(
                    self.root / "wheels/example-1.0-py3-none-any.whl", "w"
                ) as archive:
                    archive.writestr("example-1.0.dist-info/METADATA", raw)
                with self.assertRaisesRegex(proof.ProofError, code):
                    proof.hashed_requirements(self.root / "wheels", {"example": "1.0"})

    def test_normalized_historical_name_and_build_tag_are_supported(self):
        self.wheel(
            "My.Example-1.0-2-py3-none-any.whl",
            name="my-example",
            member="my_example-1.0.dist-info/METADATA",
        )
        manifest, _ = proof.hashed_requirements(
            self.root / "wheels", {"my-example": "1.0"}
        )
        self.assertEqual(manifest[0]["name"], "my-example")

    def test_noncanonical_base_refused_without_launch(self):
        base = self.root / "alias"
        base.symlink_to(sys.executable)
        with patch.object(proof, "command") as run, self.assertRaises(proof.ProofError):
            proof.verify_base(base, self.root)
        run.assert_not_called()

    def test_in_fixture_base_refused_without_launch(self):
        base = self.root / "fake-python"
        base.write_bytes(b"fixture")
        base.chmod(0o700)
        with patch.object(proof, "command") as run, self.assertRaises(proof.ProofError):
            proof.verify_base(base, self.root)
        run.assert_not_called()

    def test_local_controller_refuses_before_install_or_systemd(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            proof.subprocess, "run"
        ) as run:
            with self.assertRaises(proof.ProofError):
                proof.controller(Path(sys.executable), REPOSITORY, "a" * 40, self.root)
        run.assert_not_called()

    def test_bounded_child_is_collected_on_timeout(self):
        with self.assertRaisesRegex(proof.ProofError, "child_deadline"):
            proof.command(
                [sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
                root=self.root,
                timeout=0.1,
            )

    def test_bounded_child_failure_is_not_success(self):
        with self.assertRaisesRegex(proof.ProofError, "child_exit_7"):
            proof.command(
                [sys.executable, "-I", "-B", "-c", "raise SystemExit(7)"],
                root=self.root,
                timeout=5,
            )

    def test_disk_limit_is_not_silently_raised(self):
        meter = proof.Meter(self.root, self.root)
        with patch.object(
            proof,
            "allocated_tree",
            return_value={
                "allocated_bytes": proof.TOTAL_LIMIT + 1,
                "files": 1,
                "inodes": 1,
            },
        ):
            with self.assertRaises(proof.ProofError):
                meter.once()
        self.assertEqual(proof.MEMORY_LIMIT, 128 * 1024 * 1024)

    def test_receipt_is_bounded_and_not_ready_marker(self):
        proof.write_receipt(self.root, {"status": "failed"})
        self.assertEqual(
            json.loads((self.root / "receipts/worker.json").read_text())["status"],
            "failed",
        )
        with self.assertRaises(proof.ProofError):
            proof.write_receipt(self.root, {"value": "x" * 65536})
        self.assertFalse((self.root / "READY").exists())

    def test_import_has_no_install_or_systemd_side_effect(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import scripts.backend_release.preparation_probe",
            ],
            cwd=REPOSITORY,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")

    def test_interrupted_receipt_is_reported_without_claiming_success(self):
        file = self.root / "receipts/interrupted.json"
        self.assertEqual(proof.read_optional_receipt(file), {"status": "missing"})
        for content in ("{", "[]", "x" * 65537):
            file.write_text(content)
            self.assertEqual(
                proof.read_optional_receipt(file), {"status": "invalid_or_interrupted"}
            )

    def test_meter_failure_refuses_expensive_child_and_collects_it(self):
        (self.root / "receipts/budget-exceeded").touch()
        with self.assertRaisesRegex(proof.ProofError, "disk_budget_exceeded"):
            proof.command(
                [sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
                root=self.root,
                timeout=5,
            )

    def test_disk_samples_persist_measured_high_water(self):
        meter = proof.Meter(self.root, self.root)
        meter.once()
        saved = proof.read_optional_receipt(self.root / "receipts/resources.json")
        self.assertEqual(saved["samples"], 1)
        self.assertEqual(saved["sampled_disk_high_water"], meter.high_water)

    def test_stage_measurements_are_keyed_bounded_and_never_reset_peak(self):
        meter = proof.Meter(self.root, self.root)
        meter.begin("binary_download")
        self.set_memory(current=4096, peak=8192, events="max 9\noom_kill 0\noom 0\n")
        meter.once()
        meter.begin("wheel_metadata")
        saved = proof.read_optional_receipt(self.root / "receipts/resources.json")
        first = saved["stages"]["binary_download"]
        second = saved["stages"]["wheel_metadata"]
        self.assertTrue(first["ended"])
        self.assertGreater(first["duration_seconds"], 0)
        self.assertGreaterEqual(first["samples"], 2)
        self.assertEqual(first["sampled_current_high_water"], 4096)
        self.assertEqual(first["memory_start"]["memory.peak"], 2048)
        self.assertEqual(first["memory_latest"]["memory.peak"], 8192)
        self.assertEqual(second["memory_start"]["memory.peak"], 8192)
        self.assertEqual(first["memory_latest"]["memory.events"]["max"], 9)
        self.assertEqual(first["memory_latest"]["memory.stat"]["file"], 512)
        self.assertNotIn("unknown_future_key", first["memory_latest"]["memory.stat"])
        self.assertEqual((self.root / "memory.peak").read_text(), "8192")
        self.assertIn("total", first["sampled_disk_high_water"])
        for name in ("wheel_metadata", "uncontrolled"):
            with self.assertRaisesRegex(proof.ProofError, "stage_not_unique_or_known"):
                meter.begin(name)

    def test_over_peak_with_zero_oom_retains_metadata_and_blocks_seed(self):
        self.wheel()
        self.set_memory(peak=proof.MEMORY_LIMIT + 1)
        meter = proof.Meter(self.root, self.root)
        meter.begin("binary_download")
        receipt = {}
        with self.assertRaisesRegex(
            proof.ProofError, "measured_memory_budget_exceeded"
        ):
            proof.diagnose_wheels(self.root, {"example": "1.0"}, receipt, meter)
        saved = proof.read_optional_receipt(self.root / "receipts/worker.json")
        self.assertEqual(saved["metadata_status"], "passed")
        self.assertEqual(saved["metadata_diagnostics"]["wheels_checked"], 1)
        self.assertEqual(saved["wheel_files"][0]["name"], "example")
        for name in ("final_path_seed", "offline_install"):
            with self.assertRaisesRegex(
                proof.ProofError, "measured_memory_budget_exceeded"
            ):
                proof.enter_stage(self.root, receipt, meter, name)
        self.assertNotIn("final_path_seed", meter.stages)
        self.assertFalse((self.root / "envs/candidate").exists())

    def test_metadata_and_resource_failures_are_both_preserved(self):
        self.wheel(member="nested/example-1.0.dist-info/METADATA")
        self.set_memory(peak=proof.MEMORY_LIMIT + 1)
        meter = proof.Meter(self.root, self.root)
        receipt = {}
        with self.assertRaisesRegex(
            proof.ProofError, "measured_memory_budget_exceeded"
        ):
            proof.diagnose_wheels(self.root, {"example": "1.0"}, receipt, meter)
        saved = proof.read_optional_receipt(self.root / "receipts/worker.json")
        self.assertEqual(saved["metadata_status"], "failed")
        self.assertEqual(saved["metadata_failure"], "wheel_metadata")
        self.assertEqual(
            saved["metadata_diagnostics"]["last_archive"]["root_metadata_count"], 0
        )

    def test_memory_exact_boundary_swap_and_oom_gates(self):
        for peak, swap, events, passes in (
            (proof.MEMORY_LIMIT, 0, None, True),
            (proof.MEMORY_LIMIT + 1, 0, None, False),
            (2048, 1, None, False),
            (2048, 0, "max 1\noom 1\noom_kill 0\n", False),
        ):
            self.set_memory(peak=peak, swap=swap, events=events)
            meter = proof.Meter(self.root, self.root)
            if passes:
                meter.check_limits()
            else:
                with self.assertRaises(proof.ProofError):
                    meter.check_limits()

    def test_missing_invalid_or_oversized_cgroup_metric_refuses(self):
        for raw in ("", "file 1\nanon 1\n", "anon x\n", "x" * 16385):
            (self.root / "memory.stat").write_text(raw)
            with self.assertRaises(proof.ProofError):
                proof.memory_snapshot(self.root)

    def test_full_manifest_and_all_stage_evidence_fit_receipt_bound(self):
        expected = {}
        for index in range(73):
            name = "public_package_with_a_long_normalized_name_" + str(index)
            expected[proof.normalized_name(name)] = "1.0"
            self.wheel(
                name + "-1.0-cp313-cp313-manylinux_2_17_x86_64.whl",
                name=name,
                member=name + "-1.0.dist-info/METADATA",
            )
        diagnostics = {}
        manifest, _ = proof.hashed_requirements(
            self.root / "wheels", expected, diagnostics
        )
        meter = proof.Meter(self.root, self.root)
        for name in proof.STAGES:
            meter.begin(name)
        receipt = {
            "worker": {"wheel_files": manifest, "metadata_diagnostics": diagnostics},
            "last_resources": proof.read_optional_receipt(
                self.root / "receipts/resources.json"
            ),
        }
        self.assertLess(len(json.dumps(receipt, indent=2).encode()), 60000)

    def bundle_fixture(self):
        expected = {}
        for index in range(73):
            name = "p" + str(index)
            expected[name] = "1.0"
            self.wheel(
                name + "-1.0-py3-none-any.whl",
                name=name,
                member=name + "-1.0.dist-info/METADATA",
            )
        files, _ = proof.hashed_requirements(self.root / "wheels", expected)
        base = {
            "version": "3.13.14",
            "implementation": "cpython",
            "free_threaded": False,
            "soabi": "cpython-313-x86_64-linux-gnu",
            "system": "Linux",
            "architecture": "x86_64",
            "libc": ["glibc", "2.39"],
            "seed_version": "26.1.2",
            "seed_sha256": "c" * 64,
            "pip_version": "26.2.1",
            "executable": "/producer/python",
            "binary_sha256": "b" * 64,
        }
        manifest = {
            "schema": 1,
            "source_sha": "a" * 40,
            "requirements_sha256": "d" * 64,
            "run_id": "12",
            "attempt": "1",
            "producer": base,
            "wheels": files,
        }
        bundle = proof.artifact.create_bundle(self.root / "wheels", manifest)
        for file in files:
            (self.root / "wheels" / file["filename"]).unlink()
        return bundle, manifest, expected

    def unpack(self, manifest, **overrides):
        args = dict(
            source_sha="a" * 40,
            requirements_sha="d" * 64,
            run_id="12",
            attempt="1",
            base=manifest["producer"],
        )
        args.update(overrides)
        return proof.artifact.unpack_bundle(self.root / "wheels", **args)

    def test_bundle_binds_complete_inventory_but_not_producer_binary_path(self):
        _, manifest, expected = self.bundle_fixture()
        consumer = dict(
            manifest["producer"],
            executable="/consumer/python",
            binary_sha256="f" * 64,
            pip_version="different-base-tool",
        )
        actual, checksum = self.unpack(manifest, base=consumer)
        self.assertEqual(actual, manifest)
        self.assertEqual(len(checksum), 64)
        files, _ = proof.hashed_requirements(self.root / "wheels", expected)
        self.assertEqual(files, manifest["wheels"])

    def test_bundle_refuses_wrong_source_requirements_run_attempt_and_abi(self):
        _, manifest, _ = self.bundle_fixture()
        for overrides in (
            dict(source_sha="b" * 40),
            dict(requirements_sha="e" * 64),
            dict(run_id="13"),
            dict(attempt="2"),
            dict(base=dict(manifest["producer"], architecture="arm64")),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(
                proof.artifact.ArtifactError
            ):
                self.unpack(manifest, **overrides)
        self.assertEqual(len(list((self.root / "wheels").iterdir())), 1)

    def test_missing_corrupt_wheel_and_unknown_archive_member_refuse(self):
        bundle, manifest, _ = self.bundle_fixture()
        original = bundle.read_bytes()
        for case in ("missing", "corrupt", "extra"):
            with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(
                bundle, "w"
            ) as dest:
                for index, entry in enumerate(source.infolist()):
                    if case == "missing" and index == 1:
                        continue
                    data = source.read(entry)
                    if case == "corrupt" and index == 1:
                        data = data[:-1] + bytes([data[-1] ^ 1])
                    dest.writestr(entry, data)
                if case == "extra":
                    dest.writestr("unexpected", "x")
            with self.subTest(case=case), self.assertRaises(
                proof.artifact.ArtifactError
            ):
                self.unpack(manifest)
            for path in (self.root / "wheels").glob("*.whl"):
                path.unlink()
        self.assertFalse((self.root / "READY").exists())

    def test_outer_archive_refuses_digest_escape_link_duplicate_and_expansion(self):
        outer = self.root / "wheels/ingress.zip"
        cases = [
            ("../bundle.zip", 0, 1),
            ("bundle.zip", stat.S_IFLNK | 0o777, 1),
            ("bundle.zip", 0, 2),
            ("other.zip", 0, 1),
        ]
        for name, mode, count in cases:
            with zipfile.ZipFile(outer, "w") as archive:
                for _ in range(count):
                    entry = zipfile.ZipInfo(name)
                    entry.external_attr = mode << 16
                    if count == 2 and archive.infolist():
                        with self.assertWarns(UserWarning):
                            archive.writestr(entry, "x")
                    else:
                        archive.writestr(entry, "x")
            with self.assertRaises(proof.artifact.ArtifactError):
                proof.artifact.unpack_outer(outer, outer.parent, proof.sha256(outer))
        with self.assertRaisesRegex(proof.artifact.ArtifactError, "artifact_digest"):
            proof.artifact.unpack_outer(outer, outer.parent, "0" * 64)
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("bundle.zip", "xx")
        with patch.object(proof.artifact, "ARCHIVE_LIMIT", 1), self.assertRaisesRegex(
            proof.artifact.ArtifactError, "expanded_archive_bound"
        ):
            proof.artifact.unpack_outer(outer, outer.parent, proof.sha256(outer))

    def test_manifest_duplicate_json_keys_are_refused(self):
        with self.assertRaisesRegex(
            proof.artifact.ArtifactError, "duplicate_manifest_key"
        ):
            proof.artifact.read_json(b'{"schema":1,"schema":1}')

    def test_measured_receiver_authenticates_api_not_signed_storage(self):
        bundle, _, _ = self.bundle_fixture()
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.write(bundle, "bundle.zip")
        bundle.unlink()
        raw = data.getvalue()
        checksum = proof.hashlib.sha256(raw).hexdigest()
        metadata = {
            "id": 4,
            "expired": False,
            "workflow_run": {"id": 12, "head_sha": "a" * 40},
            "digest": "sha256:" + checksum,
            "size_in_bytes": len(raw),
        }
        redirect = urllib.error.HTTPError(
            "not-logged",
            302,
            "redirect",
            {
                "Location": "https://example.blob.core.windows.net/artifact?private=signed"
            },
            None,
        )
        with patch.dict(
            os.environ, {"GH_ARTIFACT_TOKEN": "fixture-ephemeral"}
        ), patch.object(proof.artifact.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = [
                io.BytesIO(json.dumps(metadata).encode()),
                redirect,
                io.BytesIO(raw),
            ]
            proof.artifact.receive(
                bundle.parent,
                repository="owner/repo",
                artifact_id="4",
                expected_digest=checksum,
                run_id="12",
                source_sha="a" * 40,
            )
            requests = [
                call.args[0] for call in factory.return_value.open.call_args_list
            ]
        self.assertEqual(
            requests[0].get_header("Authorization"), "Bearer fixture-ephemeral"
        )
        self.assertEqual(
            requests[1].get_header("Authorization"), "Bearer fixture-ephemeral"
        )
        self.assertIsNone(requests[2].get_header("Authorization"))
        self.assertTrue(bundle.exists())
        self.assertFalse((bundle.parent / "ingress.zip").exists())

    def test_receiver_does_not_expose_url_or_credentials_on_failure(self):
        with patch.dict(
            os.environ, {"GH_ARTIFACT_TOKEN": "fixture-ephemeral"}
        ), patch.object(proof.artifact.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = RuntimeError(
                "private=signed fixture-ephemeral"
            )
            with self.assertRaisesRegex(
                proof.artifact.ArtifactError, "^artifact_receive_failed$"
            ):
                proof.artifact.receive(
                    self.root / "wheels",
                    repository="owner/repo",
                    artifact_id="4",
                    expected_digest="f" * 64,
                    run_id="12",
                    source_sha="a" * 40,
                )

    def test_receiver_refuses_wrong_run_expiry_digest_before_download(self):
        valid = {
            "id": 4,
            "expired": False,
            "workflow_run": {"id": 12, "head_sha": "a" * 40},
            "digest": "sha256:" + "f" * 64,
            "size_in_bytes": 1024,
        }
        for change in (
            {"expired": True},
            {"id": 5},
            {"digest": "sha256:" + "e" * 64},
            {"workflow_run": {"id": 13, "head_sha": "a" * 40}},
            {"workflow_run": {"id": 12, "head_sha": "b" * 40}},
            {"size_in_bytes": proof.artifact.ARCHIVE_LIMIT + 1},
        ):
            with patch.dict(os.environ, {"GH_ARTIFACT_TOKEN": "fixture"}), patch.object(
                proof.artifact.urllib.request, "build_opener"
            ) as factory:
                factory.return_value.open.return_value = io.BytesIO(
                    json.dumps(dict(valid, **change)).encode()
                )
                with self.assertRaisesRegex(
                    proof.artifact.ArtifactError, "remote_artifact_identity"
                ):
                    proof.artifact.receive(
                        self.root / "wheels",
                        repository="owner/repo",
                        artifact_id="4",
                        expected_digest="f" * 64,
                        run_id="12",
                        source_sha="a" * 40,
                    )
                self.assertEqual(factory.return_value.open.call_count, 1)
        self.assertEqual(list((self.root / "wheels").iterdir()), [])

    def test_receiver_refuses_unreviewed_storage_redirect(self):
        metadata = {
            "id": 4,
            "expired": False,
            "workflow_run": {"id": 12, "head_sha": "a" * 40},
            "digest": "sha256:" + "f" * 64,
            "size_in_bytes": 1024,
        }
        for location in (
            "http://example.blob.core.windows.net/x",
            "https://unknown.invalid/x",
            "https://user@example.blob.core.windows.net/x",
        ):
            with patch.dict(os.environ, {"GH_ARTIFACT_TOKEN": "fixture"}), patch.object(
                proof.artifact.urllib.request, "build_opener"
            ) as factory:
                factory.return_value.open.side_effect = [
                    io.BytesIO(json.dumps(metadata).encode()),
                    urllib.error.HTTPError("", 302, "", {"Location": location}, None),
                ]
                with self.assertRaisesRegex(
                    proof.artifact.ArtifactError, "artifact_redirect_host"
                ):
                    proof.artifact.receive(
                        self.root / "wheels",
                        repository="owner/repo",
                        artifact_id="4",
                        expected_digest="f" * 64,
                        run_id="12",
                        source_sha="a" * 40,
                    )
                self.assertEqual(factory.return_value.open.call_count, 2)

    def test_namespace_failure_never_runs_install(self):
        with patch.object(proof.subprocess, "Popen") as popen:
            popen.side_effect = FileNotFoundError("namespace unavailable")
            with self.assertRaises(FileNotFoundError):
                proof.command(
                    [sys.executable, "-c", "raise SystemExit(0)"],
                    root=self.root,
                    timeout=1,
                    offline=True,
                )
        self.assertEqual(
            popen.call_args.args[0][:3], ["/usr/bin/unshare", "--net", "--"]
        )
        self.assertFalse((self.root / "envs/candidate").exists())

    def test_consumer_allowance_is_inside_128_not_extra(self):
        cap = proof.MEMORY_LIMIT - proof.CONTROL_ALLOWANCE
        self.assertEqual(cap, 96 * proof.MIB)
        self.assertEqual(
            proof.PRODUCER_MEMORY_LIMIT - proof.CONTROL_ALLOWANCE, 224 * proof.MIB
        )
        self.assertGreaterEqual(proof.CONTROL_ALLOWANCE, 21106688)
        self.set_memory(peak=cap + 1)
        meter = proof.Meter(self.root, self.root, memory_limit=cap)
        with self.assertRaisesRegex(
            proof.ProofError, "measured_memory_budget_exceeded"
        ):
            proof.enter_stage(self.root, {}, meter, "final_path_seed")

    def test_producer_scratch_is_separately_bounded(self):
        self.assertEqual(sum(proof.PRODUCER_DISK_LIMITS.values()), 512 * proof.MIB)
        meter = proof.Meter(
            self.root,
            self.root,
            memory_limit=224 * proof.MIB,
            disk_limits=proof.PRODUCER_DISK_LIMITS,
            total_limit=512 * proof.MIB,
        )
        with patch.object(
            proof,
            "allocated_tree",
            return_value={"allocated_bytes": 513 * proof.MIB, "files": 1, "inodes": 1},
        ):
            with self.assertRaises(proof.ProofError):
                meter.once()
        self.assertEqual(proof.TOTAL_LIMIT, 1280 * proof.MIB)

    def test_owned_writers_must_exit_before_cleanup(self):
        procs = self.root / "cgroup.procs"
        procs.write_text(f"{os.getpid()}\n987654321\n")
        with self.assertRaisesRegex(proof.ProofError, "owned_writers_remain"):
            proof.wait_for_owned_writers(self.root, timeout=0)
        procs.write_text(f"{os.getpid()}\n")
        proof.wait_for_owned_writers(self.root, timeout=0)

    def test_cleanup_refuses_unknown_paths_without_deleting(self):
        (self.root / "unexpected").write_text("preserve")
        with self.assertRaisesRegex(proof.ProofError, "cleanup_unknown_path"):
            proof.owned_cleanup(self.root, self.root.stat(), {})
        self.assertTrue((self.root / "unexpected").exists())

    def test_killed_writer_is_reaped_and_owned_partial_files_are_removed(self):
        # Independent private root: fake cgroup files used by other tests are not fixture data.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            for name in proof.DISK_LIMITS:
                (root / name).mkdir()
            with self.assertRaisesRegex(proof.ProofError, "child_exit_-"):
                proof.command(
                    [
                        sys.executable,
                        "-c",
                        "import os,signal,pathlib; "
                        "pathlib.Path('workspace/partial').write_text('incomplete'); "
                        "os.kill(os.getpid(), signal.SIGKILL)",
                    ],
                    root=root,
                    timeout=5,
                )
            receipt = {}
            proof.owned_cleanup(root, root.stat(), receipt)
            self.assertEqual(
                receipt["cleanup"], "owned_incomplete_paths_removed_receipts_retained"
            )
            self.assertEqual([p.name for p in root.iterdir()], ["receipts"])

    def test_workflow_has_fresh_sequential_consumer_without_download_action(self):
        workflow = (REPOSITORY / ".github/workflows/backend-ci.yml").read_text()
        producer = workflow.split("  wheel-producer-proof:")[1].split(
            "  offline-preparation-proof:"
        )[0]
        consumer = workflow.split("  offline-preparation-proof:")[1].split("  deploy:")[
            0
        ]
        self.assertIn("needs: wheel-producer-proof", consumer)
        self.assertIn("actions: read", consumer)
        self.assertNotIn("download-artifact", consumer)
        self.assertNotIn("secrets.", consumer + producer)
        for section in (producer, consumer):
            self.assertIn("runs-on: ubuntu-24.04", section)
            self.assertIn("python-version: 3.13.14", section)
            self.assertIn("timeout-minutes: 20", section)
        self.assertIn("--role producer", producer)
        self.assertIn("--role consumer", consumer)

    def exercise_controller(
        self,
        *,
        timeout=False,
        cleanup_failure=False,
        systemd_properties=None,
        live_changes=None,
        resource_changes=None,
        missing_live=(),
        missing_resources=(),
        unit_returncode=0,
        worker_cleanup=None,
        controls_rss=20612,
        expect_failure=False,
        role="consumer",
    ):
        root = self.root / ("observer-fixture-" + str(len(list(self.root.iterdir()))))
        root.mkdir(mode=0o700)
        memory = proof.memory_snapshot(self.root)
        proc = MagicMock()
        proc.pid = 12345678
        proc.poll.return_value = None if timeout else 0
        proc.wait.side_effect = (
            [subprocess.TimeoutExpired("fixture", 680), 0]
            if timeout
            else [unit_returncode, unit_returncode]
        )

        def launch(args, **_):
            root.mkdir(mode=0o700)
            (root / "receipts").mkdir()
            # Simulates already-saved live evidence, never a real Linux operation.
            worker = dict(
                memory,
                status=(
                    "wheel_producer_passed_not_release_ready"
                    if role == "producer"
                    else "offline_consumer_passed_not_release_ready"
                ),
                cleanup="owned_incomplete_paths_removed_receipts_retained",
            )
            worker["memory.peak"] = 90 * proof.MIB
            resources = dict(worker)
            worker.update(live_changes or {})
            resources.update(resource_changes or {})
            for key in missing_live:
                worker.pop(key, None)
            for key in missing_resources:
                resources.pop(key, None)
            if worker_cleanup is not None:
                worker["cleanup"] = worker_cleanup
            (root / "receipts/worker.json").write_text(json.dumps(worker))
            (root / "receipts/resources.json").write_text(json.dumps(resources))
            return proc

        original_read = Path.read_text

        def read(path, *args, **kwargs):
            if path == Path("/etc/os-release"):
                return 'VERSION_ID="24.04"'
            return original_read(path, *args, **kwargs)

        properties = dict(
            LoadState="loaded",
            MainPID="0",
            ControlGroup="",
            MemoryPeak="1024",
            Result="success",
        )
        if systemd_properties is not None:
            properties = systemd_properties
        second = (
            dict(properties, MainPID="987654321") if cleanup_failure else properties
        )
        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_OUTPUT": str(self.root / "github-output"),
            },
        ), patch.object(proof.sys, "platform", "linux"), patch.object(
            proof.os, "geteuid", return_value=0
        ), patch.object(
            proof.tempfile, "mkdtemp", return_value=str(root)
        ), patch.object(
            Path, "read_text", read
        ), patch.object(
            proof.subprocess, "Popen", side_effect=launch
        ) as popen, patch.object(
            proof.subprocess, "run"
        ) as run, patch.object(
            proof, "unit_properties", side_effect=[properties, second]
        ), patch.object(
            proof.os, "killpg"
        ) as kill, patch.object(
            proof.resource,
            "getrusage",
            return_value=SimpleNamespace(ru_maxrss=controls_rss),
        ), patch(
            "builtins.print"
        ):
            if timeout or cleanup_failure or expect_failure:
                with self.assertRaisesRegex(
                    proof.ProofError, "capacity_checkpoint_failed"
                ):
                    proof.controller(
                        Path(sys.executable),
                        REPOSITORY,
                        "a" * 40,
                        self.root / "output",
                        role=role,
                    )
            else:
                proof.controller(
                    Path(sys.executable),
                    REPOSITORY,
                    "a" * 40,
                    self.root / "output",
                    role=role,
                )
        return (
            json.loads((self.root / "output/capacity.json").read_text()),
            popen.call_args.args[0],
            run,
            kill,
            proc,
            root,
        )

    def test_successful_service_exit_has_no_active_exited_wait_deadlock(self):
        receipt, args, run, kill, proc, _ = self.exercise_controller()
        self.assertIn("--wait", args)
        self.assertIn("--pipe", args)
        self.assertIn("--property=Type=exec", args)
        self.assertNotIn("--property=RemainAfterExit=yes", args)
        self.assertNotIn("--property=Type=oneshot", args)
        self.assertEqual(proc.wait.call_args_list[0].kwargs["timeout"], 680)
        self.assertEqual(receipt["unit_returncode"], 0)
        self.assertEqual(receipt["worker"]["memory.peak"], 90 * proof.MIB)
        self.assertEqual(receipt["systemd"]["MemoryPeak"], "1024")
        self.assertTrue(receipt["controls_within_allowance"])
        kill.assert_not_called()
        self.assertTrue(
            any(
                call.args[0][:2] == ["systemctl", "stop"] for call in run.call_args_list
            )
        )

    def test_launcher_timeout_kills_owned_group_stops_unit_and_preserves_evidence(self):
        receipt, _, _, kill, proc, root = self.exercise_controller(timeout=True)
        self.assertEqual(receipt["controller_failure"], "TimeoutExpired")
        kill.assert_called_once_with(proc.pid, proof.signal.SIGKILL)
        self.assertEqual(proc.wait.call_count, 2)
        self.assertTrue((root / "receipts/worker.json").exists())
        self.assertFalse((root / "READY").exists())

    def test_uncertain_unit_cleanup_never_sweeps_fixture(self):
        receipt, _, _, _, _, root = self.exercise_controller(cleanup_failure=True)
        self.assertEqual(receipt["cleanup"], "failed_fixture_preserved")
        self.assertEqual(receipt["cleanup_failure"], "owned_processes_not_reaped")
        self.assertTrue(root.exists())

    def test_unloaded_systemd_sentinel_preserves_required_live_peak(self):
        receipt, _, run, _, _, _ = self.exercise_controller(
            role="producer",
            systemd_properties={
                "LoadState": "not-found",
                "ActiveState": "inactive",
                "ControlGroup": "",
                "ExecMainStatus": "0",
                "MainPID": "0",
                "Result": "success",
                "MemoryPeak": "[not set]",
                "MemorySwapPeak": "[not set]",
            },
        )
        self.assertEqual(
            receipt["post_exit_memory_peak"],
            {
                "status": "unavailable",
                "reason": "not_set",
            },
        )
        self.assertEqual(receipt["worker"]["memory.peak"], 90 * proof.MIB)
        self.assertEqual(receipt["last_resources"]["memory.peak"], 90 * proof.MIB)
        self.assertFalse(
            any(
                call.args[0][:2] == ["systemctl", "stop"] for call in run.call_args_list
            )
        )

    @staticmethod
    def unloaded_properties():
        return dict(
            LoadState="not-found",
            MainPID="0",
            ControlGroup="",
            MemoryPeak="[not set]",
            Result="success",
        )

    def test_post_exit_missing_and_zero_are_distinct(self):
        self.assertEqual(
            proof.post_exit_memory_peak({}),
            {"status": "unavailable", "reason": "missing"},
        )
        self.assertEqual(
            proof.post_exit_memory_peak({"MemoryPeak": "0"}),
            {"status": "available", "bytes": 0},
        )
        self.assertEqual(
            proof.post_exit_memory_peak({"MemoryPeak": "[not set]"}),
            {"status": "unavailable", "reason": "not_set"},
        )

    def test_post_exit_parser_bounds_unknown_values_without_echoing_them(self):
        for raw in (
            None,
            True,
            0,
            -1,
            "",
            "-1",
            "+1",
            "1.5",
            "NaN",
            "infinity",
            "unknown",
            "n/a",
            " 1",
            "1\n",
            "\u0661",
            "9" * 21,
            str(2**64),
            "x" * 65536,
        ):
            with self.subTest(kind=type(raw).__name__), self.assertRaisesRegex(
                proof.ProofError, "^post_exit_memory_peak_invalid$"
            ):
                proof.post_exit_memory_peak({"MemoryPeak": raw})
        with self.assertRaisesRegex(
            proof.ProofError, "^post_exit_memory_peak_invalid$"
        ):
            proof.post_exit_memory_peak(None)

    def test_missing_post_exit_observation_still_requires_live_evidence(self):
        properties = self.unloaded_properties()
        del properties["MemoryPeak"]
        receipt, *_ = self.exercise_controller(systemd_properties=properties)
        self.assertEqual(
            receipt["post_exit_memory_peak"],
            {"status": "unavailable", "reason": "missing"},
        )
        self.assertEqual(receipt["worker"]["memory.peak"], 90 * proof.MIB)

    def test_numeric_post_exit_peak_is_additional_not_replacement_evidence(self):
        cap = proof.MEMORY_LIMIT - proof.CONTROL_ALLOWANCE
        for value in (0, 1024, cap, cap + 1, 2**64 - 1):
            properties = dict(self.unloaded_properties(), MemoryPeak=str(value))
            with self.subTest(value=value):
                receipt, *_ = self.exercise_controller(
                    systemd_properties=properties, expect_failure=value > cap
                )
                self.assertEqual(
                    receipt["post_exit_memory_peak"],
                    {"status": "available", "bytes": value},
                )
                self.assertEqual(receipt["worker"]["memory.peak"], 90 * proof.MIB)
                self.assertEqual(
                    receipt["last_resources"]["memory.peak"], 90 * proof.MIB
                )

    def test_invalid_post_exit_value_is_recorded_and_refused(self):
        for raw in ("-1", "not-a-counter", "", None, True, str(2**64)):
            receipt, *_ = self.exercise_controller(
                systemd_properties=dict(self.unloaded_properties(), MemoryPeak=raw),
                expect_failure=True,
            )
            self.assertEqual(
                receipt["post_exit_memory_peak"],
                {"status": "invalid", "failure": "post_exit_memory_peak_invalid"},
            )

    def test_unavailable_post_exit_does_not_mask_missing_live_snapshots(self):
        keys = ("memory.current", "memory.peak", "memory.events", "memory.swap.peak")
        for source in ("missing_live", "missing_resources"):
            for missing in (*[(key,) for key in keys], keys):
                with self.subTest(source=source, missing=missing):
                    receipt, *_ = self.exercise_controller(
                        systemd_properties=self.unloaded_properties(),
                        expect_failure=True,
                        **{source: missing},
                    )
                    snapshot = receipt[
                        "worker" if source == "missing_live" else "last_resources"
                    ]
                    self.assertEqual(
                        proof.memory_failures(snapshot),
                        {"invalid_live_memory_evidence"},
                    )

    def test_unavailable_post_exit_does_not_mask_invalid_live_values(self):
        cases = (
            {"memory.current": -1},
            {"memory.current": False},
            {"memory.peak": "[not set]"},
            {"memory.peak": 1.5},
            {"memory.swap.peak": None},
            {"memory.swap.peak": -1},
            {"memory.events": None},
            {"memory.events": {}},
            {"memory.events": {"max": 0, "oom": 0}},
            {"memory.events": {"max": 0, "oom": 0, "oom_kill": -1}},
            {"memory.events": {"max": False, "oom": 0, "oom_kill": 0}},
        )
        for source in ("live_changes", "resource_changes"):
            for changes in cases:
                with self.subTest(source=source, changes=changes):
                    receipt, *_ = self.exercise_controller(
                        systemd_properties=self.unloaded_properties(),
                        expect_failure=True,
                        **{source: changes},
                    )
                    snapshot = receipt[
                        "worker" if source == "live_changes" else "last_resources"
                    ]
                    self.assertEqual(
                        proof.memory_failures(snapshot),
                        {"invalid_live_memory_evidence"},
                    )

    def test_unavailable_or_low_post_exit_does_not_mask_live_budget_failures(self):
        cap = proof.MEMORY_LIMIT - proof.CONTROL_ALLOWANCE
        cases = [
            {"memory.current": cap + 1},
            {"memory.peak": cap + 1},
            {"memory.swap.peak": 1},
        ]
        for event in ("oom", "oom_kill", "oom_group_kill"):
            events = dict(max=0, oom=0, oom_kill=0)
            events[event] = 1
            cases.append({"memory.events": events})
        for source in ("live_changes", "resource_changes"):
            for changes in cases:
                for optional in ("[not set]", "1"):
                    with self.subTest(
                        source=source, changes=changes, optional=optional
                    ):
                        self.exercise_controller(
                            systemd_properties=dict(
                                self.unloaded_properties(), MemoryPeak=optional
                            ),
                            expect_failure=True,
                            **{source: changes},
                        )

    def test_unavailable_post_exit_does_not_bypass_exit_status_or_cleanup(self):
        for changes in (
            {"unit_returncode": 7},
            {"unit_returncode": -9},
            {"live_changes": {"status": "failed"}},
            {"worker_cleanup": "failed_fixture_preserved"},
            {"cleanup_failure": True},
        ):
            with self.subTest(changes=changes):
                receipt, *_ = self.exercise_controller(
                    systemd_properties=self.unloaded_properties(),
                    expect_failure=True,
                    **changes,
                )
                self.assertEqual(
                    receipt["post_exit_memory_peak"]["status"], "unavailable"
                )

    def test_unavailable_post_exit_does_not_bypass_control_allowance(self):
        receipt, *_ = self.exercise_controller(
            systemd_properties=self.unloaded_properties(),
            controls_rss=proof.CONTROL_ALLOWANCE // 1024 + 1,
            expect_failure=True,
        )
        self.assertFalse(receipt["controls_within_allowance"])


if __name__ == "__main__":
    unittest.main()
