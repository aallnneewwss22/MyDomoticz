import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
DASHBOARD = ROOT / "dashboard" / "maison-dashboard-v106.html"
LAUNCHER = ROOT / "dashboard" / "maison.html"


class RecoveryDashboardTests(unittest.TestCase):
    def test_versioned_dashboard_exposes_recovery_controls(self):
        html = DASHBOARD.read_text(encoding="utf-8")
        for element_id in (
            "recovery-key-output", "recovery-key-generate",
            "recovery-key-input", "recovery-key-unlock",
        ):
            self.assertIn('id="' + element_id + '"', html)
        self.assertIn("/api/recovery/key", html)
        self.assertIn("/api/recovery/session", html)
        self.assertIn('headers["X-Recovery-Token"]', html)
        self.assertIn('method === "GET"', html)
        self.assertIn('settingsDialog.addEventListener("close"', html)

    def test_recovery_token_is_not_persisted_and_launcher_targets_v105(self):
        html = DASHBOARD.read_text(encoding="utf-8")
        self.assertNotIn("localStorage.setItem(\"recoverySessionToken\"", html)
        self.assertNotIn("localStorage.setItem(\"recovery-key", html)
        launcher = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("maison-dashboard-v106.html", launcher)
        self.assertNotIn("maison-dashboard-v104.html", launcher)


if __name__ == "__main__":
    unittest.main()
