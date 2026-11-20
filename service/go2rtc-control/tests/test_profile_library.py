import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera_profiles import normalize_camera_profiles
from profile_library import (
    PROFILE_LIBRARY_FORMAT,
    ProfileLibraryError,
    delete_profile_library_entry,
    list_profile_library,
    profile_library_filename,
    read_profile_library_entry,
    save_profile_library_entry,
)


PROFILE = {
    "name": "Équilibré",
    "width": 1280,
    "height": 720,
    "fps": 10,
    "bitrate_kbps": 400,
}


class ProfileLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_filename_is_derived_safely_from_profile_name(self):
        self.assertEqual(profile_library_filename("Équilibré"), "Équilibré.json")
        self.assertEqual(profile_library_filename("../secret"), "secret.json")
        self.assertEqual(profile_library_filename("Profil mobile"), "Profil mobile.json")

    def test_save_and_read_profile_use_common_library_format(self):
        saved = save_profile_library_entry(self.directory, PROFILE)
        self.assertEqual(saved["filename"], "Équilibré.json")
        path = self.directory / saved["filename"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["format"], PROFILE_LIBRARY_FORMAT)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["profile"]["name"], "Équilibré")
        loaded = read_profile_library_entry(self.directory, saved["filename"])
        self.assertEqual(loaded["profile"], saved["profile"])

    def test_list_returns_only_profile_metadata(self):
        save_profile_library_entry(self.directory, PROFILE)
        entries = list_profile_library(self.directory)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["valid"])
        self.assertEqual(entries[0]["name"], "Équilibré")

    def test_existing_entry_requires_explicit_overwrite(self):
        save_profile_library_entry(self.directory, PROFILE)
        with self.assertRaises(FileExistsError):
            save_profile_library_entry(self.directory, PROFILE)
        replacement = dict(PROFILE, bitrate_kbps=600)
        save_profile_library_entry(self.directory, replacement, overwrite=True)
        self.assertEqual(
            read_profile_library_entry(self.directory, "Équilibré.json")["profile"]["bitrate_kbps"],
            600,
        )

    def test_filename_collision_between_different_names_is_rejected(self):
        save_profile_library_entry(self.directory, PROFILE)
        with self.assertRaises(ProfileLibraryError):
            save_profile_library_entry(
                self.directory, dict(PROFILE, name="Equilibre"), overwrite=True
            )

    def test_invalid_profile_values_are_rejected(self):
        with self.assertRaises(ProfileLibraryError):
            save_profile_library_entry(self.directory, dict(PROFILE, width=1111))

    def test_corrupt_entry_is_listed_as_invalid_and_can_be_deleted(self):
        path = self.directory / "corrupt.json"
        path.write_text("{", encoding="utf-8")
        entries = list_profile_library(self.directory)
        self.assertEqual(entries, [{"filename": "corrupt.json", "name": "corrupt", "valid": False}])
        delete_profile_library_entry(self.directory, "corrupt.json")
        self.assertFalse(path.exists())

    def test_path_traversal_and_symlinks_are_rejected(self):
        with self.assertRaises(ProfileLibraryError):
            read_profile_library_entry(self.directory, "../outside.json")
        outside = self.directory / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        link = self.directory / "link.json"
        link.symlink_to(outside)
        with self.assertRaises(FileNotFoundError):
            read_profile_library_entry(self.directory, "link.json")




SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("profile_library_api_test", SERVER_PATH)
server_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server_module)

TOKEN = "profile-library-test-token-" + ("x" * 32)


class FakeSessionManager:
    @contextmanager
    def camera_guard(self, camera_id):
        yield


class ProfileLibraryHTTPApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_dir.name)
        profiles, _ = normalize_camera_profiles(None, None, "1080p")
        self.cameras = {
            "salon": {
                "source": "rtsp://camera.invalid/stream1",
                "audio_enabled": True,
                "quality": "1080p",
                "profiles": profiles,
                "default_profile_id": "native",
                "selected_profile_id": "native",
            }
        }
        self.patches = [
            patch.object(server_module, "PROFILE_LIBRARY_DIR", self.directory),
            patch.object(server_module, "read_token", return_value=TOKEN),
            patch.object(server_module, "load_camera_settings", side_effect=lambda: self.cameras),
            patch.object(server_module, "save_camera_settings", side_effect=lambda cameras: None),
            patch.object(server_module, "SESSION_MANAGER", FakeSessionManager()),
        ]
        for item in self.patches:
            item.start()
        self.httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:%s" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, token=TOKEN):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_library_http_api_create_read_replace_and_delete(self):
        profile = dict(PROFILE)
        status, created = self.request(
            "POST", "/api/profile-library", {"profile": profile}
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["filename"], "Équilibré.json")

        status, listing = self.request("GET", "/api/profile-library")
        self.assertEqual(status, 200)
        self.assertEqual(listing["files"][0]["name"], "Équilibré")

        status, loaded = self.request("GET", "/api/profile-library/" + urllib.parse.quote("Équilibré.json"))
        self.assertEqual(status, 200)
        self.assertEqual(loaded["profile"]["name"], "Équilibré")

        status, conflict = self.request(
            "POST", "/api/profile-library", {"profile": profile}
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["filename"], "Équilibré.json")

        status, replaced = self.request(
            "PUT", "/api/profile-library/" + urllib.parse.quote("Équilibré.json"),
            {"profile": dict(profile, bitrate_kbps=600)},
        )
        self.assertEqual(status, 200)
        self.assertEqual(replaced["profile"]["bitrate_kbps"], 600)

        status, deleted = self.request("DELETE", "/api/profile-library/" + urllib.parse.quote("Équilibré.json"))
        self.assertEqual(status, 200)
        self.assertEqual(deleted["deleted"], "Équilibré.json")

    def test_import_creates_a_camera_local_profile_and_can_replace_it(self):
        status, imported = self.request(
            "POST", "/api/cameras/salon/profiles/import", {"profile": PROFILE}
        )
        self.assertEqual(status, 201)
        profile_id = imported["profile"]["id"]
        self.assertRegex(profile_id, r"^[0-9a-f]{32}$")
        self.assertEqual(self.cameras["salon"]["selected_profile_id"], "native")

        replacement = dict(PROFILE, name="Salon HD", bitrate_kbps=650)
        status, updated = self.request(
            "POST", "/api/cameras/salon/profiles/import",
            {"profile": replacement, "replace_profile_id": profile_id},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["profile"]["id"], profile_id)
        self.assertEqual(updated["profile"]["name"], "Salon HD")

    def test_import_rejects_resolution_above_camera_native_quality(self):
        self.cameras["salon"]["quality"] = "720p"
        incompatible = dict(PROFILE, width=1920, height=1080)
        status, result = self.request(
            "POST", "/api/cameras/salon/profiles/import", {"profile": incompatible}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", result)
        self.assertEqual(
            list(self.cameras["salon"]["profiles"]),
            ["native"],
        )

    def test_library_requires_the_control_token(self):
        status, result = self.request("GET", "/api/profile-library", token=None)
        self.assertEqual(status, 401)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
