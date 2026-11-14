import unittest
from pathlib import Path

import yaml

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

    def test_example_yaml_files_are_valid_and_use_disjoint_ports(self):
        production = yaml.safe_load(self.read("go2rtc.yaml.example"))
        testing = yaml.safe_load(self.read("go2rtc-test.yaml.example"))
        self.assertEqual(production["api"]["listen"], "127.0.0.1:1984")
        self.assertEqual(production["rtsp"]["listen"], ":8554")
        self.assertEqual(production["webrtc"]["listen"], ":8555")
        self.assertEqual(testing["api"]["listen"], "127.0.0.1:1987")
        self.assertEqual(testing["rtsp"]["listen"], ":8556")
        self.assertEqual(testing["webrtc"]["listen"], ":8557")
        self.assertEqual(production["streams"], {})
        self.assertEqual(testing["streams"], {})

    def test_test_control_environment_targets_test_instance(self):
        env = self.read("go2rtc-control-test.env.example")
        self.assertIn("GO2RTC_API=http://127.0.0.1:1987", env)
        self.assertIn("GO2RTC_CONFIG=/home/pi/go2rtc-test/go2rtc.yaml", env)
        self.assertIn("TRANSCODE_RTSP_PORT=8556", env)
        self.assertIn("CONTROL_PORT=1986", env)

    def test_migration_document_covers_both_registries_tokens_and_rollback(self):
        guide = self.read("MIGRATION.md")
        for required in (
            "/var/lib/go2rtc-control/cameras.json",
            "/var/lib/go2rtc-control-test/cameras.json",
            "TOKEN_FILE",
            "camera_sejour",
            "camera_test_rtsp_probe",
            "1987",
            "8556",
            "Retour arrière détaillé",
            "go2rtc-control-test.service",
        ):
            self.assertIn(required, guide)
        self.assertIn("Ne jamais fusionner les registres", guide)

    def test_installer_fails_closed_on_mismatched_production_config(self):
        installer = self.read("install.sh")
        self.assertIn("GO2RTC_CONFIG", installer)
        self.assertIn("go2rtc.env", installer)
        self.assertIn("Configuration de production incohérente", installer)


if __name__ == "__main__":
    unittest.main()
