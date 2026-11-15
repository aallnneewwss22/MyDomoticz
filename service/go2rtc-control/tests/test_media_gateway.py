"""Tests for the authenticated, narrowly scoped go2rtc media gateway."""
import importlib.util
import http.client
import json
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class FakeGo2rtcHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            b'<!doctype html><html><head></head><body>'
            b'<script type="module" src="./video-stream.js"></script>'
            b'</body></html>'
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


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
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeGo2rtcHandler)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        self.gateway = MediaGateway(
            "http://127.0.0.1:%s" % self.upstream.server_address[1]
        )
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
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream_thread.join(timeout=2)

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

    def test_player_ticket_is_exchanged_for_a_cookie_and_clean_player_url(self):
        status, result = self.request({"camera": "salon"})
        self.assertEqual(status, 201)
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_address[1], timeout=3
        )
        connection.request("GET", result["path"])
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        cookie = response.getheader("Set-Cookie")
        self.assertIn("go2rtc_media_salon=", cookie)
        self.assertIn("HttpOnly", cookie)
        html = response.read().decode("utf-8")
        self.assertIn("history.replaceState", html)
        self.assertIn("/media/salon/stream.html?src=salon", html)
        self.assertNotIn("ticket=", html)

        connection.request(
            "GET", "/media/salon/stream.html?src=salon&mode=webrtc%2Cmse%2Chls",
            headers={"Cookie": cookie.split(";", 1)[0]},
        )
        second = connection.getresponse()
        self.assertEqual(second.status, 200)
        second.read()
        connection.close()

    def test_media_assets_require_a_session_cookie(self):
        request = urllib.request.Request(
            self.base_url + "/media/salon/video-stream.js", method="GET"
        )
        try:
            urllib.request.urlopen(request, timeout=3)
            self.fail("A media asset must not be public.")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 401)


if __name__ == "__main__":
    unittest.main()
