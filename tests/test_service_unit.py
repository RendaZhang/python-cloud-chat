import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT_PATH = ROOT / "deploy" / "cloudchat.service"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "backend-ci.yml"


def parse_unit(path: Path) -> dict[str, dict[str, list[str]]]:
    sections: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    section = ""

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key, separator, value = line.partition("=")
        if not section or not separator:
            raise AssertionError(f"Invalid unit line: {raw_line}")
        sections[section][key].append(value)

    return sections


class CloudChatServiceUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit_text = UNIT_PATH.read_text(encoding="utf-8")
        cls.workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.unit = parse_unit(UNIT_PATH)
        cls.service = cls.unit["Service"]

    def assert_directive(self, name: str, value: str):
        self.assertEqual(self.service.get(name), [value])

    def test_runs_as_dedicated_user_on_loopback(self):
        self.assert_directive("User", "cloudchat")
        self.assert_directive("Group", "cloudchat")
        self.assertNotIn("User=root", self.unit_text)

        exec_start = self.service["ExecStart"][0]
        self.assertIn("--bind 127.0.0.1:5000", exec_start)
        self.assertIn("--worker-tmp-dir /run/cloudchat", exec_start)
        self.assertNotIn("0.0.0.0:5000", exec_start)

    def test_preserves_root_owned_configuration_boundary(self):
        self.assert_directive("WorkingDirectory", "/opt/cloudchat")
        self.assert_directive("EnvironmentFile", "/etc/cloudchat/cloudchat.env")
        self.assert_directive("StateDirectory", "cloudchat")
        self.assert_directive("StateDirectoryMode", "0750")
        self.assert_directive("RuntimeDirectory", "cloudchat")
        self.assert_directive("RuntimeDirectoryMode", "0750")
        self.assert_directive("UMask", "0077")

    def test_removes_privileges_and_limits_filesystem_access(self):
        expected = {
            "CapabilityBoundingSet": "",
            "AmbientCapabilities": "",
            "NoNewPrivileges": "true",
            "PrivateTmp": "true",
            "PrivateDevices": "true",
            "ProtectSystem": "strict",
            "ProtectHome": "true",
            "ProtectControlGroups": "true",
            "ProtectKernelModules": "true",
            "ProtectKernelTunables": "true",
            "ProtectKernelLogs": "true",
            "ProtectClock": "true",
            "ProtectHostname": "true",
            "ProtectProc": "invisible",
            "RestrictSUIDSGID": "true",
            "RestrictRealtime": "true",
            "RestrictNamespaces": "true",
            "LockPersonality": "true",
            "RemoveIPC": "true",
            "MemoryDenyWriteExecute": "true",
            "KeyringMode": "private",
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assert_directive(name, value)

    def test_keeps_only_required_network_families_and_resource_limits(self):
        self.assert_directive("RestrictAddressFamilies", "AF_UNIX AF_INET AF_INET6")
        self.assert_directive("SystemCallArchitectures", "native")
        self.assert_directive("MemoryHigh", "250M")
        self.assert_directive("MemoryMax", "300M")
        self.assert_directive("TasksMax", "128")
        self.assert_directive("OOMScoreAdjust", "100")

    def test_deploy_workflow_owns_preflight_install_and_rollback(self):
        required_markers = (
            "deploy/cloudchat.service",
            "cloudchat-preflight.service",
            "127.0.0.1:5001",
            "RuntimeMaxSec=180",
            "systemd-analyze verify",
            "useradd \\",
            "getent passwd cloudchat | cut -d: -f6",
            "getent passwd cloudchat | cut -d: -f7",
            "cmp --silent",
            "mv --force",
            "rollback_cloudchat_unit",
            "CapBnd",
            "127.0.0.1:5000",
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.workflow_text)


if __name__ == "__main__":
    unittest.main()
