"""Portable stdlib tests only; real installs are confined to the isolated CI job."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
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


if __name__ == "__main__":
    unittest.main()
