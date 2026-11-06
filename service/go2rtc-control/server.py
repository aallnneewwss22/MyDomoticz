#!/usr/bin/env python3
"""Authenticated local control API for go2rtc streams."""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

STREAM_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
GO2RTC_API = os.environ.get("GO2RTC_API", "http://127.0.0.1:1984").rstrip("/")
GO2RTC_CONFIG = Path(os.environ.get("GO2RTC_CONFIG", "/home/pi/go2rtc-test/go2rtc.yaml"))
SOURCE_REGISTRY = Path(os.environ.get("SOURCE_REGISTRY", "/var/lib/go2rtc-control/cameras.json"))
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
        raise RuntimeError("Impossible de lire le jeton d'accès.") from exc
    if len(token) < 32:
        raise RuntimeError("Le jeton d'accès est invalide.")
    return token


def load_go2rtc_sources() -> dict[str, str]:
    """Read supported simple source strings from go2rtc YAML."""
    try:
        data = yaml.safe_load(GO2RTC_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ControlError("Configuration go2rtc illisible.") from exc
    if not isinstance(data, dict):
        raise ControlError("La configuration go2rtc doit être un dictionnaire.")
    streams = data.get("streams", {})
    if not isinstance(streams, dict):
        raise ControlError("La section streams du YAML doit être un dictionnaire.")
    sources: dict[str, str] = {}
    for name, source in streams.items():
        if isinstance(name, str) and STREAM_NAME.fullmatch(name) and isinstance(source, str) and source.strip():
            sources[name] = source.strip()
    return sources


def _write_registry_atomically(sources: dict[str, str]) -> None:
    """Create the private registry without exposing sources in logs or API output."""
    SOURCE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".cameras-", dir=str(SOURCE_REGISTRY.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(sources, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # The registry is initialized once. Never replace an existing registry:
        # it may contain sources whose streams were globally stopped.
        try:
            os.link(temporary, SOURCE_REGISTRY)
        except FileExistsError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def ensure_source_registry() -> None:
    """Migrate YAML sources on first start; preserve registry on every later start."""
    if SOURCE_REGISTRY.exists():
        return
    sources = load_go2rtc_sources()
    _write_registry_atomically(sources)


def load_sources() -> dict[str, str]:
    """Read the independent registry, never the mutable go2rtc YAML."""
    try:
        data = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlError("Registre local des caméras illisible.") from exc
    if not isinstance(data, dict):
        raise ControlError("Registre local des caméras invalide.")
    sources: dict[str, str] = {}
    for name, source in data.items():
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
    server_version = "go2rtc-control/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        # Never log query parameters: a start request contains an RTSP source.
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
        try:
            expected = "Bearer " + read_token()
        except RuntimeError:
            self.send_json(503, {"error": "Jeton d'accès indisponible."})
            return False
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
        if len(parts) != 4 or parts[:2] != ["api", "cameras"] or parts[3] != action:
            self.send_json(404, {"error": "Route inconnue."})
            return
        name = urllib.parse.unquote(parts[2])
        if not STREAM_NAME.fullmatch(name):
            self.send_json(400, {"error": "Nom de flux invalide."})
            return
        try:
            sources = load_sources()
            if name not in sources:
                self.send_json(404, {"error": "Caméra absente du registre local."})
                return
            if action == "status":
                self.send_json(200, {"enabled": stream_exists(name)})
                return
            if action == "stop":
                # go2rtc DELETE also removes the YAML stream definition.
                # The independent registry above is deliberately retained.
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
    ensure_source_registry()
    ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), Handler).serve_forever()
