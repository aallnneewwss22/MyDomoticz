import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camera_settings_backup import (
    CAMERA_BACKUP_FORMAT, CameraBackupError, ensure_backup_directory,
    make_backup, preview_restore, read_backup, validate_backup, write_backup,
)


def sample_camera(source="rtsp://camera/stream1"):
    return {
        "source": source,
        "quality": "1080p",
        "audio_enabled": False,
        "ptz": {"host": "192.0.2.10", "port": 80, "username": "user", "password": "secret"},
        "profiles": {
            "native": {"id": "native", "name": "Natif", "type": "native"}
        },
        "default_profile_id": "native",
        "selected_profile_id": "native",
        "ptz_upside_down": True,
    }


class CameraSettingsBackupTests(unittest.TestCase):
    def test_round_trip_preserves_camera_secrets_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = make_backup({"front": sample_camera()})
            write_backup(root, "cameras.json", backup)
            restored = read_backup(root, "cameras.json")
            self.assertEqual(restored["cameras"]["front"]["ptz"]["password"], "secret")
            self.assertFalse(restored["cameras"]["front"]["audio_enabled"])
            self.assertTrue(restored["cameras"]["front"]["ptz_upside_down"])

    def test_directory_and_file_permissions_are_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private"
            ensure_backup_directory(root)
            write_backup(root, "cameras.json", make_backup({"front": sample_camera()}))
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual((root / "cameras.json").stat().st_mode & 0o777, 0o600)

    def test_preview_never_contains_secret_values(self):
        before = {"front": sample_camera()}
        after = copy.deepcopy(before)
        after["front"]["source"] = "rtsp://different/stream1"
        result = preview_restore(before, after)
        serialized = json.dumps(result)
        self.assertIn("source RTSP", serialized)
        self.assertNotIn("rtsp://", serialized)
        self.assertNotIn("onvif-secret", serialized)
        self.assertFalse(result["secrets_displayed"])

    def test_preview_reports_added_removed_and_modified_cameras(self):
        current = {"old": sample_camera(), "same": sample_camera()}
        incoming = {"new": sample_camera(), "same": sample_camera("rtsp://changed/stream1")}
        result = preview_restore(current, incoming)
        self.assertEqual(result["added"], ["new"])
        self.assertEqual(result["removed"], ["old"])
        self.assertEqual(result["modified"], [{"camera": "same", "fields": ["source RTSP"]}])

    def test_rejects_unsupported_version(self):
        backup = make_backup({"front": sample_camera()})
        backup["version"] = 2
        with self.assertRaises(CameraBackupError):
            validate_backup(backup)

    def test_rejects_invalid_camera_and_ptz_data(self):
        backup = make_backup({"front": sample_camera()})
        backup["cameras"]["front"]["ptz"]["port"] = 70000
        with self.assertRaises(CameraBackupError):
            validate_backup(backup)

    def test_rejects_unknown_fields_instead_of_silently_dropping_them(self):
        backup = make_backup({"front": sample_camera()})
        backup["cameras"]["front"]["gateway_token"] = "not-allowed"
        with self.assertRaises(CameraBackupError):
            validate_backup(backup)

    def test_library_is_not_part_of_backup_schema(self):
        backup = make_backup({"front": sample_camera()})
        self.assertNotIn("profile_library", backup)
        self.assertEqual(backup["format"], CAMERA_BACKUP_FORMAT)


if __name__ == "__main__":
    unittest.main()
