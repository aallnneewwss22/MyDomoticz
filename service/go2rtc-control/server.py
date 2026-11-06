#!/usr/bin/env python3
"""Small authenticated control API for locally configured go2rtc streams."""
from __future__ import annotations

import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

STREAM_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
GO2RTC_API = os.environ.get("GO2RTC_API", "http://127.0.0.1:1984").rstrip("/")
GO2RTC_CONFIG = Path(os.environ.get("GO2RTC_CONFIG", "/home/pi/go2rtc-test/go2rtc.yaml"))
TOKEN_FILE = Path(os.environ.get("TOKEN_FILE", "/etc/go2rtc-control/token"))
DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://192.168.1.21:8080").rstrip("/")
CONTROL_HOST = os.environ.get("CONTROL_HOST", "0.0.0.0")
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "1985"))


class ControlError(Exception):
    pass


def read_token() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Impossible de lire le jeton ({TOKEN_FILE}).") from exc
    if len(token) < 32:
        raise RuntimeError("Le jeton doit contenir au moins 32 caractères.")
    return token


def load_sources() -> dict[str, str]:
    try:
        data = yaml.safe_load(GO2RTC_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ControlError("Configuration go2rtc illisible.") from exc
    streams = data.get("streams", {})
    if not isinstance(streams, dict):
        raise ControlError("La section streams du YAML doit être un dictionnaire.")
    sources: dict[str, str] = {}
    for name, source in streams.items():
        if isinstance(name, str) and STREAM_NAME.fullmatch(name) and isinstance(source, str) and source.strip():
            sources[name] = source.strip()
    return sources


def go2rtc_request(method: str, path: str) -> tuple[int, object]:
    request = urllib.request.Request(GO2RTC_API + path, method=method)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ControlError("Le serveur go2rtc ne répond pas.") from exc
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    return status, payload


def stream_exists(name: str) -> bool:
    status, payload = go2rtc_request("GET", "/api/streams")
    if status != 200:
        raise ControlError(f"Lecture de l'état go2rtc impossible (HTTP {status}).")
    if isinstance(payload, dict):
        return name in payload
    if isinstance(payload, list):
        return any(isinstance(item, dict) and item.get("name") == name for item in payload)
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "go2rtc-control/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        # Ne jamais journaliser les paramètres de requête, qui pourraient contenir une source.
        super().log_message("%s", self.path.split("?", 1)[0])

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin == DASHBOARD_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", DASHBOARD_ORIGIN)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        origin = self.headers.get("Origin", "")
        if origin and origin != DASHBOARD_ORIGIN:
            self.send_json(403, {"error": "Origine non autorisée."})
            return False
        expected = "Bearer " + read_token()
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, expected):
            self.send_json(401, {"error": "Jeton absent ou invalide."})
            return False
        return True

    def do_OPTIONS(self) -> None:
        if self.headers.get("Origin", "") != DASHBOARD_ORIGIN:
            self.send_json(403, {"error": "Origine non autorisée."})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", DASHBOARD_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def handle_camera(self, action: str) -> None:
        if not self.authorized():
            return
        parts = urllib.parse.urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "cameras"]:
            self.send_json(404, {"error": "Route inconnue."})
            return
        name = urllib.parse.unquote(parts[2]) if len(parts) == 3 else urllib.parse.unquote(parts[2])
        if not STREAM_NAME.fullmatch(name):
            self.send_json(400, {"error": "Nom de flux invalide."})
            return
        try:
            sources = load_sources()
            if name not in sources:
                self.send_json(404, {"error": "Flux absent de la configuration locale."})
                return
            if action == "status":
                self.send_json(200, {"enabled": stream_exists(name)})
                return
            if action == "stop":
                status, _ = go2rtc_request("DELETE", "/api/streams?" + urllib.parse.urlencode({"src": name}))
                if status not in (200, 204):
                    raise ControlError(f"Arrêt refusé par go2rtc (HTTP {status}).")
                self.send_json(200, {"enabled": False})
                return
            if action == "start":
                query = urllib.parse.urlencode({"name": name, "src": sources[name]})
                status, _ = go2rtc_request("PUT", "/api/streams?" + query)
                if status not in (200, 201, 204):
                    raise ControlError(f"Redémarrage refusé par go2rtc (HTTP {status}).")
                self.send_json(200, {"enabled": True})
                return
            self.send_json(404, {"error": "Action inconnue."})
        except ControlError as exc:
            self.send_json(502, {"error": str(exc)})

    def do_GET(self) -> None:
        self.handle_camera("status")

    def do_POST(self) -> None:
        action = urllib.parse.urlsplit(self.path).path.rstrip("/").split("/")[-1]
        self.handle_camera(action)


if __name__ == "__main__":
    read_token()
    ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), Handler).serve_forever()
