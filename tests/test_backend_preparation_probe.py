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

    def wheel(
        self, filename="example-1.0-py3-none-any.whl", name="example", version="1.0"
    ):
        destination = self.root / "wheels" / filename
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(
                "example-1.0.dist-info/METADATA",
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
        self.wheel(name="my_example")
        self.wheel("another-1.0-py3-none-any.whl", name="my-example")
        with self.assertRaises(proof.ProofError):
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


if __name__ == "__main__":
    unittest.main()
