import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "server.py"
os.environ.setdefault("TOKEN_FILE", "/tmp/go2rtc-control-recovery-api-test-token")
spec = importlib.util.spec_from_file_location("go2rtc_control_recovery_api", MODULE_PATH)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class RecoveryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_values = {
            "TOKEN_FILE": server_module.TOKEN_FILE,
            "SETTINGS_BACKUP_DIR": server_module.SETTINGS_BACKUP_DIR,
            "DASHBOARD_ORIGINS": server_module.DASHBOARD_ORIGINS,
            "RECOVERY_AUTH": server_module.RECOVERY_AUTH,
        }
        self.token = "normal-control-token-" + ("x" * 32)
        self.token_file = root / "token"
        self.token_file.write_text(self.token, encoding="utf-8")
        server_module.TOKEN_FILE = self.token_file
        server_module.SETTINGS_BACKUP_DIR = root / "backups"
        server_module.DASHBOARD_ORIGINS = {"http://dashboard.test"}
        server_module.RECOVERY_AUTH = server_module.RecoveryAuth(root / "state" / "recovery-key.json")
        server_module.ensure_settings_backup_dir()
        server_module.write_settings_backup("known.json", {
            "format": "mydomoticz-settings",
            "version": 1,
            "settings": {
                "refreshIntervalSeconds": "30", "theme": "auto", "pageNames": "{}",
                "cameraControlUrl": "", "cameraControlToken": "restored-token",
                "ptzGainPc": "0.2", "ptzSpeedPc": "0.5",
                "ptzGainMobile": "0.2", "ptzSpeedMobile": "0.5",
            },
        })
        self.recovery_key = server_module.RECOVERY_AUTH.create_or_rotate_key()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.httpd.server_address[1])

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        for name, value in self.old_values.items():
            setattr(server_module, name, value)
        self.temp.cleanup()

    def request(self, path, *, method="GET", payload=None, headers=None):
        request_headers = {"Origin": "http://dashboard.test"}
        if headers:
            request_headers.update(headers)
        body = None
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.headers, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, error.headers, json.loads(error.read().decode("utf-8"))

    def create_recovery_session(self):
        status, _, data = self.request("/api/recovery/session", method="POST", payload={"key": self.recovery_key})
        self.assertEqual(status, 200)
        return data["recoveryToken"]

    def test_recovery_session_can_list_and_read_backups(self):
        session = self.create_recovery_session()
        headers = {"X-Recovery-Token": session}
        status, response_headers, listing = self.request("/api/settings-backups", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(listing["files"], ["known.json"])
        self.assertEqual(response_headers.get("Cache-Control"), "no-store")
        status, _, backup = self.request("/api/settings-backups/known.json", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(backup["settings"]["cameraControlToken"], "restored-token")

    def test_recovery_session_cannot_write_backups(self):
        session = self.create_recovery_session()
        status, _, _ = self.request(
            "/api/settings-backups/forbidden.json", method="PUT",
            payload={"format": "mydomoticz-settings", "version": 1, "settings": {}},
            headers={"X-Recovery-Token": session},
        )
        self.assertEqual(status, 401)
        self.assertFalse((server_module.SETTINGS_BACKUP_DIR / "forbidden.json").exists())

    def test_recovery_session_cannot_access_camera_commands(self):
        session = self.create_recovery_session()
        status, _, _ = self.request("/api/cameras/salon/status", headers={"X-Recovery-Token": session})
        self.assertEqual(status, 401)

    def test_recovery_session_is_required_for_backup_listing(self):
        status, _, _ = self.request("/api/settings-backups")
        self.assertEqual(status, 401)

    def test_recovery_exchange_rejects_untrusted_or_missing_origin(self):
        request = urllib.request.Request(
            self.base + "/api/recovery/session",
            data=json.dumps({"key": self.recovery_key}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": "http://evil.test"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 403)
        request = urllib.request.Request(
            self.base + "/api/recovery/session",
            data=json.dumps({"key": self.recovery_key}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 403)

    def test_invalid_recovery_key_is_rejected(self):
        status, _, _ = self.request("/api/recovery/session", method="POST", payload={"key": "invalid"})
        self.assertEqual(status, 401)

    def test_rate_limited_exchange_returns_429(self):
        for _ in range(5):
            status, _, _ = self.request("/api/recovery/session", method="POST", payload={"key": "A" * 43})
            self.assertEqual(status, 401)
        status, _, _ = self.request("/api/recovery/session", method="POST", payload={"key": "A" * 43})
        self.assertEqual(status, 429)

    def test_recovery_header_is_advertised_for_cors_preflight(self):
        request = urllib.request.Request(
            self.base + "/api/recovery/session", headers={
                "Origin": "http://dashboard.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            }, method="OPTIONS",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 204)
            self.assertIn("X-Recovery-Token", response.headers["Access-Control-Allow-Headers"])

    def test_only_normal_bearer_can_generate_or_rotate_key(self):
        status, _, _ = self.request("/api/recovery/key", method="POST", payload={}, headers={})
        self.assertEqual(status, 401)
        session = self.create_recovery_session()
        status, _, _ = self.request(
            "/api/recovery/key", method="POST", payload={},
            headers={"X-Recovery-Token": session},
        )
        self.assertEqual(status, 401)
        status, _, result = self.request(
            "/api/recovery/key", method="POST", payload={},
            headers={"Authorization": "Bearer " + self.token},
        )
        self.assertEqual(status, 201)
        self.assertRegex(result["recoveryKey"], r"^[A-Za-z0-9_-]{43}$")
        self.assertFalse(server_module.RECOVERY_AUTH.is_session_valid(session))


if __name__ == "__main__":
    unittest.main()
