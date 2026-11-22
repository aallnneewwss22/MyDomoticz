import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

MODULE_PATH = Path(__file__).parents[1] / "server.py"
os.environ.setdefault("TOKEN_FILE", "/tmp/go2rtc-control-camera-backup-api-test-token")
spec = importlib.util.spec_from_file_location("go2rtc_control_camera_backup_api", MODULE_PATH)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


def camera_settings(source="rtsp://user:password@camera/stream1"):
    return {
        "source": source,
        "audio_enabled": False,
        "quality": "1080p",
        "ptz": {"host": "192.0.2.10", "port": 80, "username": "onvif-user", "password": "onvif-secret"},
        "profiles": {"native": {"id": "native", "name": "Natif", "type": "native"}},
        "default_profile_id": "native",
        "selected_profile_id": "native",
        "ptz_upside_down": True,
    }


class CameraSettingsBackupApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_values = {
            "TOKEN_FILE": server_module.TOKEN_FILE,
            "SOURCE_REGISTRY": server_module.SOURCE_REGISTRY,
            "CAMERA_SETTINGS_BACKUP_DIR": server_module.CAMERA_SETTINGS_BACKUP_DIR,
            "SETTINGS_BACKUP_DIR": server_module.SETTINGS_BACKUP_DIR,
            "PROFILE_LIBRARY_DIR": server_module.PROFILE_LIBRARY_DIR,
            "DASHBOARD_ORIGINS": server_module.DASHBOARD_ORIGINS,
        }
        self.token = "camera-backup-api-token-" + ("x" * 32)
        self.token_file = root / "token"
        self.token_file.write_text(self.token, encoding="utf-8")
        server_module.TOKEN_FILE = self.token_file
        server_module.SOURCE_REGISTRY = root / "cameras.json"
        server_module.CAMERA_SETTINGS_BACKUP_DIR = root / "camera-backups"
        server_module.SETTINGS_BACKUP_DIR = root / "general-backups"
        server_module.PROFILE_LIBRARY_DIR = root / "profile-library"
        server_module.DASHBOARD_ORIGINS = {"http://dashboard.test"}
        server_module.save_camera_settings({"front": camera_settings()})
        server_module.ensure_camera_backup_directory(server_module.CAMERA_SETTINGS_BACKUP_DIR)
        server_module.PROFILE_LIBRARY_DIR.mkdir()
        self.library_file = server_module.PROFILE_LIBRARY_DIR / "shared.json"
        self.library_file.write_text('{"keep":true}', encoding="utf-8")
        server_module.SETTINGS_BACKUP_DIR.mkdir()
        self.general_backup = server_module.SETTINGS_BACKUP_DIR / "general.json"
        self.general_backup.write_text('{"keep":"general"}', encoding="utf-8")
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
        request_headers.setdefault("Authorization", "Bearer " + self.token)
        request = urllib.request.Request(self.base + path, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, response.headers, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, error.headers, json.loads(error.read().decode("utf-8"))

    def create_backup(self):
        status, _, result = self.request("/api/camera-settings-backups/front.json", method="PUT")
        self.assertEqual(status, 201)
        self.assertEqual(result["camera_count"], 1)

    def test_backup_list_and_metadata_never_return_camera_secrets(self):
        self.create_backup()
        status, _, listing = self.request("/api/camera-settings-backups")
        self.assertEqual(status, 200)
        self.assertEqual(listing["files"], ["front.json"])
        status, _, metadata = self.request("/api/camera-settings-backups/front.json")
        self.assertEqual(status, 200)
        serialized = json.dumps(metadata)
        self.assertNotIn("password", serialized)
        self.assertNotIn("rtsp://", serialized)
        self.assertEqual(metadata["camera_count"], 1)

    def test_preview_returns_only_redacted_change_metadata(self):
        self.create_backup()
        status, _, preview = self.request(
            "/api/camera-settings-backups/front.json/preview", method="POST", payload={}
        )
        self.assertEqual(status, 200)
        serialized = json.dumps(preview)
        self.assertNotIn("password", serialized)
        self.assertNotIn("onvif-secret", serialized)
        self.assertNotIn("rtsp://", serialized)
        self.assertFalse(preview["secrets_displayed"])

    def test_preview_reports_active_transcode_sessions(self):
        self.create_backup()
        active = {"state": "active", "session_count": 1, "active_profile": None, "last_error": None}
        with patch.object(server_module.SESSION_MANAGER, "status", return_value=active):
            status, _, preview = self.request(
                "/api/camera-settings-backups/front.json/preview", method="POST", payload={}
            )
        self.assertEqual(status, 200)
        self.assertEqual(preview["session_conflicts"], [
            {"camera": "front", "state": "active", "session_count": 1}
        ])

    def test_restore_replaces_camera_registry_but_not_library_or_general_backups(self):
        self.create_backup()
        changed = camera_settings("rtsp://new-user:new-password@other-camera/stream1")
        changed["audio_enabled"] = True
        server_module.save_camera_settings({"front": changed})
        _, _, preview = self.request(
            "/api/camera-settings-backups/front.json/preview", method="POST", payload={}
        )
        with patch.object(server_module, "stream_exists", return_value=False), patch.object(server_module, "load_go2rtc_sources", return_value={}):
            status, _, result = self.request(
                "/api/camera-settings-backups/front.json/restore",
                method="POST", payload={"confirmed": True, "createdAt": preview["createdAt"], "registry_revision": preview["registry_revision"]},
            )
        self.assertEqual(status, 200)
        self.assertEqual(result["camera_count"], 1)
        restored = server_module.load_camera_settings()["front"]
        self.assertEqual(restored["source"], "rtsp://user:password@camera/stream1")
        self.assertFalse(restored["audio_enabled"])
        self.assertEqual(restored["ptz"]["password"], "onvif-secret")
        self.assertTrue(restored["ptz_upside_down"])
        self.assertEqual(self.library_file.read_text(encoding="utf-8"), '{"keep":true}')
        self.assertEqual(self.general_backup.read_text(encoding="utf-8"), '{"keep":"general"}')

    def test_restore_rejects_camera_registry_changes_since_preview(self):
        self.create_backup()
        _, _, preview = self.request(
            "/api/camera-settings-backups/front.json/preview", method="POST", payload={}
        )
        changed = camera_settings("rtsp://changed-after-preview@camera/stream1")
        server_module.save_camera_settings({"front": changed})
        status, _, result = self.request(
            "/api/camera-settings-backups/front.json/restore",
            method="POST",
            payload={
                "confirmed": True,
                "createdAt": preview["createdAt"],
                "registry_revision": preview["registry_revision"],
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(result["result"], "stale_preview")
        self.assertEqual(server_module.load_camera_settings()["front"]["source"], changed["source"])

    def test_active_transcode_session_blocks_restore_without_changing_registry(self):
        self.create_backup()
        changed = camera_settings("rtsp://changed@camera/stream1")
        server_module.save_camera_settings({"front": changed})
        _, _, preview = self.request(
            "/api/camera-settings-backups/front.json/preview", method="POST", payload={}
        )
        with patch.object(server_module.SESSION_MANAGER, "assert_native_source_change_allowed", side_effect=server_module.SessionConflict("Session active")), patch.object(server_module, "stream_exists", return_value=False):
            status, _, result = self.request(
                "/api/camera-settings-backups/front.json/restore",
                method="POST", payload={"confirmed": True, "createdAt": preview["createdAt"], "registry_revision": preview["registry_revision"]},
            )
        self.assertEqual(status, 409)
        self.assertEqual(result["result"], "blocked")
        self.assertEqual(server_module.load_camera_settings()["front"]["source"], changed["source"])

    def test_recovery_session_cannot_access_camera_backups(self):
        status, _, _ = self.request(
            "/api/camera-settings-backups",
            headers={"Authorization": "", "X-Recovery-Token": "recovery-session-only"},
        )
        self.assertEqual(status, 401)

    def test_ptz_orientation_is_migrated_to_server_registry(self):
        legacy = server_module.load_camera_settings()
        legacy["front"].pop("ptz_upside_down", None)
        server_module.save_camera_settings(legacy)
        status, _, initial = self.request("/api/cameras/front/ptz-orientation")
        self.assertEqual(status, 200)
        self.assertFalse(initial["configured"])
        self.assertFalse(initial["upside_down"])
        status, _, saved = self.request(
            "/api/cameras/front/ptz-orientation",
            method="POST", payload={"upside_down": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(saved["upside_down"])
        status, _, current = self.request("/api/cameras/front/ptz-orientation")
        self.assertEqual(status, 200)
        self.assertTrue(current["configured"])
        self.assertTrue(current["upside_down"])

    def test_delete_rejects_encoded_path_traversal(self):
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text('{"keep":true}', encoding="utf-8")
        status, _, _ = self.request(
            "/api/camera-settings-backups/..%2Foutside.json", method="DELETE"
        )
        self.assertEqual(status, 400)
        self.assertTrue(outside.exists())

    def test_camera_backup_files_have_private_permissions(self):
        self.create_backup()
        self.assertEqual(server_module.CAMERA_SETTINGS_BACKUP_DIR.stat().st_mode & 0o777, 0o700)
        self.assertEqual((server_module.CAMERA_SETTINGS_BACKUP_DIR / "front.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
