"""HTTP integration tests for the transcoding session API."""
import importlib.util
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("go2rtc_control_api_test", SERVER_PATH)
server_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server_module)

from session_manager import SessionManager, SessionUnavailable

TOKEN = "test-api-token-" + ("x" * 40)
PROFILE = {
    "source": "1080p", "width": 854, "height": 480,
    "fps": 10, "bitrate_kbps": 400,
}
OTHER_PROFILE = {
    "source": "1080p", "width": 640, "height": 360,
    "fps": 5, "bitrate_kbps": 250,
}


class FakeProducer:
    def __init__(self):
        self.active = set()
        self.starts = []
        self.stops = []

    def start(self, camera_id, profile):
        self.starts.append((camera_id, dict(profile)))
        self.active.add(camera_id)
        return True

    def stop(self, camera_id):
        self.stops.append(camera_id)
        self.active.discard(camera_id)

    def health(self, camera_id):
        return camera_id in self.active


class TranscodeHTTPApiTests(unittest.TestCase):
    def setUp(self):
        self.producer = FakeProducer()
        self.manager = SessionManager(
            self.producer.start, self.producer.stop, self.producer.health
        )
        self.patches = [
            patch.object(server_module, "SESSION_MANAGER", self.manager),
            patch.object(server_module, "TRANSCODE_ENGINE_AVAILABLE", True),
            patch.object(server_module, "read_token", return_value=TOKEN),
            patch.object(server_module, "load_camera_settings", return_value={
                "salon": {"source": "rtsp://camera.invalid/live",
                          "audio_enabled": True, "quality": "1080p"}
            }),
        ]
        for item in self.patches:
            item.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:%s" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()

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

    def test_acquire_and_join_share_one_producer(self):
        path = "/api/cameras/salon/transcode/acquire"
        status, first = self.request("POST", path, {"profile": PROFILE})
        self.assertEqual(status, 200)
        self.assertEqual(first["result"], "started")
        status, second = self.request("POST", path, {"profile": PROFILE})
        self.assertEqual(status, 200)
        self.assertEqual(second["result"], "joined")
        self.assertEqual(len(self.producer.starts), 1)

    def test_profile_conflict_does_not_create_a_second_session(self):
        path = "/api/cameras/salon/transcode/acquire"
        self.request("POST", path, {"profile": PROFILE})
        status, result = self.request("POST", path, {"profile": OTHER_PROFILE})
        self.assertEqual(status, 409)
        self.assertEqual(result["result"], "profile_conflict")
        self.assertEqual(self.manager.status("salon")["session_count"], 1)
        self.assertEqual(len(self.producer.starts), 1)

    def test_native_quality_mismatch_is_rejected(self):
        profile = dict(PROFILE, source="720p")
        status, result = self.request(
            "POST", "/api/cameras/salon/transcode/acquire", {"profile": profile}
        )
        self.assertEqual(status, 409)
        self.assertEqual(result["result"], "native_quality_mismatch")
        self.assertEqual(self.manager.status("salon")["session_count"], 0)

    def test_heartbeat_and_release_use_session_token(self):
        _, session = self.request(
            "POST", "/api/cameras/salon/transcode/acquire", {"profile": PROFILE}
        )
        credentials = {
            "session_id": session["session_id"],
            "session_token": session["session_token"],
        }
        status, result = self.request(
            "POST", "/api/cameras/salon/transcode/heartbeat", credentials
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["result"], "renewed")
        status, result = self.request(
            "POST", "/api/cameras/salon/transcode/release", credentials
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["result"], "released")
        self.assertFalse(self.producer.health("salon"))

    def test_wrong_session_token_is_rejected(self):
        _, session = self.request(
            "POST", "/api/cameras/salon/transcode/acquire", {"profile": PROFILE}
        )
        status, result = self.request(
            "POST", "/api/cameras/salon/transcode/heartbeat",
            {"session_id": session["session_id"], "session_token": "wrong"},
        )
        self.assertEqual(status, 401)
        self.assertIn("error", result)

    def test_status_and_health_routes(self):
        status, state = self.request("GET", "/api/cameras/salon/transcode/status")
        self.assertEqual(status, 200)
        self.assertEqual(state["state"], "idle")
        self.assertTrue(state["engine_available"])
        status, health = self.request("GET", "/api/cameras/salon/transcode/health")
        self.assertEqual(status, 200)
        self.assertFalse(health["producer_active"])

    def test_unknown_camera_is_rejected(self):
        status, result = self.request(
            "GET", "/api/cameras/inconnue/transcode/status"
        )
        self.assertEqual(status, 404)
        self.assertIn("error", result)

    def test_global_bearer_token_is_required(self):
        status, _ = self.request(
            "GET", "/api/cameras/salon/transcode/status", token=None
        )
        self.assertEqual(status, 401)

    def test_native_quality_change_is_blocked_during_session(self):
        self.request(
            "POST", "/api/cameras/salon/transcode/acquire", {"profile": PROFILE}
        )
        status, result = self.request(
            "POST", "/api/cameras/salon/quality", {"quality": "720p"}
        )
        self.assertEqual(status, 409)
        self.assertEqual(result["result"], "blocked")

    def test_engine_unavailable_returns_503_without_creating_session(self):
        def unavailable(camera_id, profile):
            raise SessionUnavailable("Moteur non disponible pour ce test.")
        unavailable_manager = SessionManager(
            unavailable, lambda camera_id: None, lambda camera_id: False
        )
        with patch.object(server_module, "SESSION_MANAGER", unavailable_manager):
            status, result = self.request(
                "POST", "/api/cameras/salon/transcode/acquire",
                {"profile": PROFILE},
            )
        self.assertEqual(status, 503)
        self.assertEqual(result["result"], "error")
        self.assertEqual(unavailable_manager.status("salon")["session_count"], 0)
        self.assertEqual(unavailable_manager.status("salon")["state"], "idle")


if __name__ == "__main__":
    unittest.main()
