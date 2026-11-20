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
        self.assertIn("PROFILE_LIBRARY_DIR=/var/lib/go2rtc-control-test/profile-library", env)
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

    def test_test_control_requires_test_go2rtc_and_uses_isolated_paths(self):
        unit = self.read("go2rtc-control-test.service")
        self.assertIn("After=network-online.target go2rtc-test.service", unit)
        self.assertIn("Requires=go2rtc-test.service", unit)
        self.assertIn("/etc/go2rtc-control-test/go2rtc-control-test.env", unit)
        self.assertIn("/opt/go2rtc-control-test/server.py", unit)
        self.assertNotIn("go2rtc.service", unit.replace("go2rtc-test.service", ""))

    def test_installer_deploys_both_environments_without_registry_commands(self):
        installer = self.read("install.sh")
        for required in (
            "go2rtc.service",
            "go2rtc-control.service",
            "go2rtc-test.service",
            "go2rtc-control-test.service",
            "/opt/go2rtc-control-test",
            "/etc/go2rtc-control-test",
            "127.0.0.1:1987",
            "127.0.0.1",
            "/var/lib/go2rtc-control-test/cameras.json",
            "/var/lib/go2rtc-control-test/profile-library",
            "go2rtc-control-show-token --test",
        ):
            self.assertIn(required, installer)
        self.assertNotIn("> /var/lib/go2rtc-control/cameras.json", installer)
        self.assertNotIn("> /var/lib/go2rtc-control-test/cameras.json", installer)
        self.assertIn("Do not create, replace, copy, or merge either SOURCE_REGISTRY", installer)

    def test_token_helper_selects_test_environment_explicitly(self):
        helper = self.read("show-token.sh")
        self.assertIn("--test", helper)
        self.assertIn("/etc/go2rtc-control-test/go2rtc-control-test.env", helper)
        self.assertIn("/etc/go2rtc-control-test/token", helper)

    def test_token_helper_uses_the_selected_environment_not_inherited_token_file(self):
        helper = self.read("show-token.sh")
        self.assertIn('ENV_FILE="/etc/go2rtc-control-test/go2rtc-control-test.env"', helper)
        self.assertIn('ENV_FILE="/etc/go2rtc-control/go2rtc-control.env"', helper)
        self.assertIn('TOKEN_FILE="$DEFAULT_TOKEN_FILE"', helper)
        self.assertNotIn('if [[ -z "${TOKEN_FILE+x}" ]]', helper)
        self.assertIn(r"""printf '%s\n' "${token_lines[0]}""" , helper)

    def test_installer_fails_closed_on_mismatched_production_config(self):
        installer = self.read("install.sh")
        self.assertIn("GO2RTC_CONFIG", installer)
        self.assertIn("go2rtc.env", installer)
        self.assertIn("Configuration de production incohérente", installer)


if __name__ == "__main__":
    unittest.main()
