"""Unit tests for finite ONVIF RelativeMove joystick steps."""
from pathlib import Path
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch


SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("go2rtc_control_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server)


class FakePTZ:
    def __init__(self):
        self.calls = []
        self.request = None

    def create_type(self, name):
        self.calls.append(("create_type", name))
        return SimpleNamespace()

    def RelativeMove(self, request):
        self.calls.append(("RelativeMove", request))
        self.request = request

    def ContinuousMove(self, request):
        raise AssertionError("ContinuousMove must not be used")


class RelativeMoveTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "ptz": {"host": "camera.invalid", "port": 2020,
                    "username": "test-user", "password": "test-password"}
        }
        self.ptz = FakePTZ()

    def test_sends_one_finite_pan_tilt_relative_move(self):
        with patch.object(server, "_ptz_connection",
                          return_value=(self.ptz, "profile-token")):
            server.ptz_move(self.settings, {"pan": 1, "tilt": -0.5, "speed": 0.5})

        self.assertEqual(self.ptz.calls[0], ("create_type", "RelativeMove"))
        self.assertEqual(self.ptz.request.ProfileToken, "profile-token")
        self.assertAlmostEqual(self.ptz.request.Translation["PanTilt"]["x"], 0.08)
        self.assertAlmostEqual(self.ptz.request.Translation["PanTilt"]["y"], -0.04)
        self.assertEqual(self.ptz.request.Speed["PanTilt"], {"x": 0.5, "y": 0.5})
        self.assertFalse(any(name == "ContinuousMove" for name, *_ in self.ptz.calls))

    def test_rejects_a_zero_vector_without_sending_a_command(self):
        with patch.object(server, "_ptz_connection",
                          return_value=(self.ptz, "profile-token")):
            with self.assertRaises(server.ControlError):
                server.ptz_move(self.settings, {"pan": 0, "tilt": 0})
        self.assertEqual(self.ptz.calls, [])

    def test_rejects_out_of_range_vector(self):
        with patch.object(server, "_ptz_connection",
                          return_value=(self.ptz, "profile-token")):
            with self.assertRaises(server.ControlError):
                server.ptz_move(self.settings, {"pan": 1.1, "tilt": 0})
        self.assertEqual(self.ptz.calls, [])


if __name__ == "__main__":
    unittest.main()
