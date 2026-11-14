import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class EnvironmentSeparationTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_production_control_requires_production_go2rtc(self):
        unit = self.read("go2rtc-control.service")
        self.assertIn("After=network-online.target go2rtc.service", unit)
        self.assertIn("Requires=go2rtc.service", unit)
        self.assertNotIn("go2rtc-test.service", unit)

    def test_production_go2rtc_uses_an_independent_binary_and_config(self):
        unit = self.read("go2rtc.service")
        self.assertIn("/usr/local/bin/go2rtc", unit)
        self.assertIn("/etc/go2rtc/go2rtc.env", unit)
        self.assertIn("${GO2RTC_CONFIG}", unit)

    def test_test_environment_uses_distinct_ports(self):
        test_yaml = self.read("go2rtc-test.yaml.example")
        test_env = self.read("go2rtc-control-test.env.example")
        self.assertIn("127.0.0.1:1987", test_yaml)
        self.assertIn(":8556", test_yaml)
        self.assertIn(":8557", test_yaml)
        self.assertIn("http://127.0.0.1:1987", test_env)
        self.assertIn("TRANSCODE_RTSP_PORT=8556", test_env)
        self.assertIn("CONTROL_PORT=1986", test_env)

    def test_migration_document_preserves_registries_and_requires_backup(self):
        guide = self.read("MIGRATION.md")
        self.assertIn("/root/go2rtc-separation-backup", guide)
        self.assertIn("/var/lib/go2rtc-control/cameras.json", guide)
        self.assertIn("Ne jamais faire pointer les deux services vers le même registre", guide)


if __name__ == "__main__":
    unittest.main()
