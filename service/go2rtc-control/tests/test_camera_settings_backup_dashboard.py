import unittest
from pathlib import Path

ROOT = Path(__file__).parents[3]
DASHBOARD = ROOT / "dashboard" / "maison-dashboard-v106.html"
LAUNCHER = ROOT / "dashboard" / "maison.html"


class CameraSettingsBackupDashboardTests(unittest.TestCase):
    def test_dashboard_exposes_independent_camera_backup_controls(self):
        html = DASHBOARD.read_text(encoding="utf-8")
        for element_id in (
            "camera-settings-backup-name", "camera-settings-backup-list",
            "camera-settings-backup-refresh", "camera-settings-backup-save",
            "camera-settings-backup-preview-button", "camera-settings-backup-restore",
            "camera-settings-backup-delete", "camera-settings-backup-preview",
        ):
            self.assertIn('id="' + element_id + '"', html)
        self.assertIn("/api/camera-settings-backups", html)
        self.assertIn("La bibliothèque commune de profils", html)
        self.assertIn("ptz-orientation", html)
        self.assertIn("data.session_conflicts.length", html)

    def test_camera_backup_uses_bearer_token_not_recovery_session(self):
        html = DASHBOARD.read_text(encoding="utf-8")
        start = html.index("async function cameraSettingsBackupRequest")
        end = html.index("function selectedCameraBackupName", start)
        helper = html[start:end]
        self.assertIn("Authorization: \"Bearer \" + token", helper)
        self.assertNotIn("recoverySessionToken", helper)

    def test_launcher_targets_v106(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("maison-dashboard-v106.html", launcher)
        self.assertNotIn("maison-dashboard-v105.html", launcher)


if __name__ == "__main__":
    unittest.main()
