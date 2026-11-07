import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("TOKEN_FILE", "/tmp/go2rtc-control-test-token")
MODULE_PATH = Path(__file__).parents[1] / "server.py"
spec = importlib.util.spec_from_file_location("go2rtc_control_ptz", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)



class ServiceSandboxTests(unittest.TestCase):
    def test_zeep_cache_uses_writable_systemd_state_directory(self):
        unit_path = Path(__file__).parents[1] / "go2rtc-control.service"
        unit = unit_path.read_text(encoding="utf-8")
        self.assertIn("StateDirectory=go2rtc-control", unit)
        self.assertIn("Environment=XDG_CACHE_HOME=/var/lib/go2rtc-control/cache", unit)
        self.assertIn("ProtectHome=read-only", unit)

class PTZValidationTests(unittest.TestCase):
    def test_normalized_movement_values_are_accepted(self):
        self.assertEqual(module._ptz_float(0.75, "pan"), 0.75)
        self.assertEqual(module._ptz_float(-1, "tilt"), -1.0)
        self.assertEqual(module._ptz_float(0.5, "speed", 0.05, 1.0), 0.5)

    def test_out_of_range_values_are_rejected(self):
        with self.assertRaises(module.ControlError):
            module._ptz_float(1.1, "pan")
        with self.assertRaises(module.ControlError):
            module._ptz_float(0, "speed", 0.05, 1.0)

    def test_invalid_numeric_values_are_rejected(self):
        with self.assertRaises(module.ControlError):
            module._ptz_float("fast", "pan")


class PTZConnectionTests(unittest.TestCase):
    def setUp(self):
        self.old_camera = module.ONVIFCamera
        module.PTZ_CLIENT_CACHE.clear()

    def tearDown(self):
        module.ONVIFCamera = self.old_camera
        module.PTZ_CLIENT_CACHE.clear()

    def test_connection_selects_a_profile_with_ptz_configuration(self):
        fake_ptz = object()
        class FakeMedia:
            def GetProfiles(self):
                return [
                    SimpleNamespace(token="media-only", PTZConfiguration=None),
                    SimpleNamespace(token="ptz-profile", PTZConfiguration=object()),
                ]
        class FakeCamera:
            def __init__(self, *args):
                self.args = args
            def create_media_service(self):
                return FakeMedia()
            def create_ptz_service(self):
                return fake_ptz
        module.ONVIFCamera = FakeCamera
        settings = {"ptz": {"host": "192.0.2.10", "port": 80, "username": "user", "password": "secret"}}
        service, token = module._ptz_connection(settings)
        self.assertIs(service, fake_ptz)
        self.assertEqual(token, "ptz-profile")
        self.assertEqual(len(module.PTZ_CLIENT_CACHE), 1)


    def test_failed_relative_move_logs_safe_detail_and_invalidates_cache(self):
        username, password = "onvif-user", "private-password"
        settings = {"ptz": {"host": "192.0.2.12", "port": 2020, "username": username, "password": password}}
        key = module._ptz_cache_key(settings)

        class FakePTZ:
            def create_type(self, name):
                return SimpleNamespace()
            def RelativeMove(self, request):
                raise RuntimeError(f"SOAP fault for {username} {password}")

        module.PTZ_CLIENT_CACHE[key] = (FakePTZ(), "profile")
        with self.assertLogs("go2rtc-control.ptz", level="WARNING") as captured:
            with self.assertRaises(module.ControlError):
                module.ptz_move(settings, {"pan": 1, "tilt": 0, "speed": 0.5})

        self.assertNotIn(key, module.PTZ_CLIENT_CACHE)
        log_text = " ".join(captured.output)
        self.assertIn("RelativeMove", log_text)
        self.assertIn("SOAP fault", log_text)
        self.assertNotIn(username, log_text)
        self.assertNotIn(password, log_text)

    def test_connection_cache_reuses_the_onvif_session(self):
        calls = []
        class FakeMedia:
            def GetProfiles(self):
                return [SimpleNamespace(token="profile", PTZConfiguration=object())]
        class FakeCamera:
            def __init__(self, *args):
                calls.append(args)
            def create_media_service(self):
                return FakeMedia()
            def create_ptz_service(self):
                return object()
        module.ONVIFCamera = FakeCamera
        settings = {"ptz": {"host": "192.0.2.11", "port": 80, "username": "", "password": ""}}
        first = module._ptz_connection(settings)
        second = module._ptz_connection(settings)
        self.assertIs(first[0], second[0])
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
