"""Tests for the authenticated, narrowly scoped go2rtc media gateway."""
import importlib.util
import json
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from media_gateway import MediaGateway, MediaGatewayError

SERVER_PATH = ROOT / "server.py"
SPEC = importlib.util.spec_from_file_location("go2rtc_media_gateway_api_test", SERVER_PATH)
server_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server_module)

TOKEN = "test-media-ticket-token-" + ("x" * 40)


class MediaGatewayTicketTests(unittest.TestCase):
    def setUp(self):
        self.gateway = MediaGateway("http://127.0.0.1:1984")

    def test_ticket_is_single_use_and_bound_to_camera(self):
        ticket = self.gateway.issue_ticket("salon")
        with self.assertRaises(MediaGatewayError):
            self.gateway._exchange_ticket(ticket, "entree")
        session = self.gateway._exchange_ticket(ticket, "salon")
        self.assertTrue(session)
        with self.assertRaises(MediaGatewayError):
            self.gateway._exchange_ticket(ticket, "salon")

    def test_ticket_expiration_is_enforced(self):
        ticket = self.gateway.issue_ticket("salon")
        self.gateway._tickets[ticket] = ("salon", 0)
        with self.assertRaises(MediaGatewayError):
            self.gateway._exchange_ticket(ticket, "salon")

    def test_transcode_source_is_limited_to_its_camera(self):
        self.assertTrue(self.gateway._valid_source("salon", "salon"))
        self.assertTrue(self.gateway._valid_source("salon_transcode", "salon"))
        self.assertFalse(self.gateway._valid_source("entree", "salon"))


class MediaTicketHTTPTests(unittest.TestCase):
    def setUp(self):
        self.gateway = MediaGateway("http://127.0.0.1:1984")
        self.patches = [
            patch.object(server_module, "MEDIA_GATEWAY", self.gateway),
            patch.object(server_module, "read_token", return_value=TOKEN),
            patch.object(server_module, "load_camera_settings", return_value={
                "salon": {"source": "rtsp://camera.invalid/stream1"}
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

    def request(self, payload, token=TOKEN):
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            self.base_url + "/api/media/ticket", data=data,
            headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_ticket_requires_control_bearer(self):
        status, result = self.request({"camera": "salon"}, token=None)
        self.assertEqual(status, 401)
        self.assertIn("error", result)

    def test_ticket_is_issued_only_for_registered_camera(self):
        status, result = self.request({"camera": "unknown"})
        self.assertEqual(status, 404)
        self.assertIn("error", result)

    def test_ticket_response_contains_a_player_path_not_the_bearer(self):
        status, result = self.request({"camera": "salon"})
        self.assertEqual(status, 201)
        self.assertTrue(result["path"].startswith("/media/salon/stream.html?"))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(result["path"]).query)
        self.assertIn("ticket", query)
        self.assertEqual(query["src"], ["salon"])
        self.assertNotIn(TOKEN, result["path"])
        session = self.gateway._exchange_ticket(query["ticket"][0], "salon")
        self.assertTrue(session)


if __name__ == "__main__":
    unittest.main()
