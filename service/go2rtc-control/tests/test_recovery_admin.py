import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "recovery-key-admin.py"
SPEC = importlib.util.spec_from_file_location("recovery_key_admin", SCRIPT)
ADMIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADMIN)


class RecoveryAdminCommandTests(unittest.TestCase):
    def test_reads_only_recovery_key_path_from_environment_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "service.env"
            env_file.write_text(
                "TOKEN_FILE=/secret/token\n"
                "RECOVERY_KEY_FILE='/private/recovery/key.json'\n"
                "MALICIOUS=$(touch /tmp/should-not-run)\n",
                encoding="utf-8",
            )
            self.assertEqual(
                ADMIN.configured_key_path(env_file, Path("/default/key.json")),
                Path("/private/recovery/key.json"),
            )

    def test_uses_default_when_setting_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "service.env"
            env_file.write_text("TOKEN_FILE=/secret/token\n", encoding="utf-8")
            fallback = Path("/default/recovery.json")
            self.assertEqual(ADMIN.configured_key_path(env_file, fallback), fallback)

    def test_missing_environment_file_uses_default(self):
        fallback = Path("/default/recovery.json")
        self.assertEqual(
            ADMIN.configured_key_path(Path("/does/not/exist"), fallback), fallback
        )

    def test_requires_root_before_any_key_operation(self):
        with mock.patch.object(ADMIN.os, "geteuid", return_value=1000):
            with self.assertRaises(SystemExit) as caught:
                ADMIN.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_requires_interactive_terminal_to_prevent_secret_redirect(self):
        with mock.patch.object(ADMIN.os, "geteuid", return_value=0), \
             mock.patch.object(ADMIN.sys.stdout, "isatty", return_value=False):
            with self.assertRaises(SystemExit) as caught:
                ADMIN.main([])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
