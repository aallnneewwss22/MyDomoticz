"""Narrow authenticated media gateway for the go2rtc v1.9.15 web player.

The go2rtc HTTP API remains bound to loopback. The dashboard obtains a
single-use ticket through the existing Bearer-authenticated control API;
the first player request exchanges it for an HttpOnly, camera-scoped cookie.
Only the viewer assets, WebSocket signaling, and HLS media paths are proxied.
WebRTC media itself continues to travel directly over the configured
go2rtc WebRTC transport ports.
"""
from __future__ import annotations

import http.client
import re
import secrets
import select
import socket
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from http.server import BaseHTTPRequestHandler


class MediaGatewayError(Exception):
    """A media request is invalid or not authorized."""


class MediaGateway:
    TICKET_TTL = 45
    SESSION_TTL = 28800
    COOKIE_PREFIX = "go2rtc_media_"
    VIEWER_ASSETS = {
        "stream.html", "stream.js", "video-stream.js", "video-rtc.js",
        "stream.css", "video-stream.css", "favicon.ico",
    }

    def __init__(self, go2rtc_api: str):
        parsed = urlsplit(go2rtc_api)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("La passerelle média exige une API go2rtc HTTP locale.")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self._lock = threading.RLock()
        self._tickets: dict[str, tuple[str, float]] = {}
        self._sessions: dict[str, tuple[str, float]] = {}

    def issue_ticket(self, camera: str) -> str:
        ticket = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._tickets[ticket] = (camera, now + self.TICKET_TTL)
        return ticket

    def _prune(self, now: float) -> None:
        self._tickets = {key: value for key, value in self._tickets.items() if value[1] > now}
        self._sessions = {key: value for key, value in self._sessions.items() if value[1] > now}

    def _exchange_ticket(self, ticket: str, camera: str) -> str:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            item = self._tickets.get(ticket)
            if item is None or item[0] != camera or item[1] <= now:
                raise MediaGatewayError("Autorisation de lecture absente ou expirée.")
            self._tickets.pop(ticket, None)
            session = secrets.token_urlsafe(32)
            self._sessions[session] = (camera, now + self.SESSION_TTL)
            return session

    def _cookie_sessions(self, handler: BaseHTTPRequestHandler) -> dict[str, str]:
        cookie = SimpleCookie()
        try:
            cookie.load(handler.headers.get("Cookie", ""))
        except Exception:
            return {}
        result = {}
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            for key, morsel in cookie.items():
                if not key.startswith(self.COOKIE_PREFIX):
                    continue
                camera = key[len(self.COOKIE_PREFIX):]
                session = morsel.value
                stored = self._sessions.get(session)
                if stored and stored[0] == camera and stored[1] > now:
                    self._sessions[session] = (camera, now + self.SESSION_TTL)
                    result[camera] = session
        return result

    @staticmethod
    def _send_error(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
        body = (message + "\n").encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        if handler.command != "HEAD":
            handler.wfile.write(body)

    @staticmethod
    def _read_query(handler: BaseHTTPRequestHandler) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlsplit(handler.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    @staticmethod
    def _valid_source(source: str, camera: str) -> bool:
        return source in (camera, camera + "_transcode")

    @staticmethod
    def _same_origin_request(handler: BaseHTTPRequestHandler) -> bool:
        """Reject cross-origin reuse of a camera media cookie."""
        fetch_site = handler.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site and fetch_site != "same-origin":
            return False
        origin = handler.headers.get("Origin", "")
        if not origin:
            return True
        parsed = urlsplit(origin)
        host = handler.headers.get("Host", "").lower()
        scheme = "https" if handler.headers.get("X-Forwarded-Proto", "").lower() == "https" else "http"
        return parsed.scheme == scheme and parsed.netloc.lower() == host

    def _proxy_http(
        self, handler: BaseHTTPRequestHandler, upstream_path: str,
        cookie_header=None, rewrite_viewer: bool = False,
    ) -> None:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=15)
        headers = {}
        for key, value in handler.headers.items():
            if key.lower() in {
                "host", "connection", "upgrade", "cookie", "authorization",
                "origin", "content-length", "transfer-encoding", "accept-encoding",
            }:
                continue
            headers[key] = value
        headers["Host"] = f"{self.host}:{self.port}"
        headers["Connection"] = "close"
        try:
            connection.request(handler.command, upstream_path, headers=headers)
            response = connection.getresponse()
            body = response.read()
            if rewrite_viewer:
                text = body.decode("utf-8", errors="replace")
                # go2rtc 1.9.15 viewer assets are root-relative. Keep the
                # viewer inside the camera-scoped gateway while leaving its
                # /api/ws and /api/hls endpoints on the gateway origin.
                prefix = handler._media_prefix
                for asset in self.VIEWER_ASSETS - {"stream.html"}:
                    text = text.replace('"/' + asset + '"', '"' + prefix + "/" + asset + '"')
                    text = text.replace("'/" + asset + "'", "'" + prefix + "/" + asset + "'")
                clean_url = getattr(handler, "_media_clean_url", None)
                if clean_url:
                    script = '<script>history.replaceState(null, "", "' + clean_url + '");</script>'
                    text = re.sub(r"(<head\b[^>]*>)", lambda match: match.group(1) + script, text, count=1, flags=re.IGNORECASE)
                body = text.encode("utf-8")
            handler.send_response(response.status, response.reason)
            content_type = response.getheader("Content-Type")
            if content_type:
                handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(body)))
            handler.send_header("Cache-Control", "no-store")
            if cookie_header:
                handler.send_header("Set-Cookie", cookie_header)
            handler.end_headers()
            if handler.command != "HEAD":
                handler.wfile.write(body)
        except (OSError, http.client.HTTPException) as exc:
            self._send_error(handler, 502, "Le lecteur go2rtc est momentanément indisponible.")
        finally:
            connection.close()

    def _proxy_websocket(self, handler: BaseHTTPRequestHandler, upstream_path: str) -> None:
        handler.close_connection = True
        upstream = None
        try:
            upstream = socket.create_connection((self.host, self.port), timeout=10)
            request = f"GET {upstream_path} HTTP/1.1\r\n"
            upstream.sendall(request.encode("ascii"))
            forwarded = []
            for key, value in handler.headers.items():
                if key.lower() in {"host", "origin", "cookie", "authorization", "connection", "upgrade"}:
                    continue
                forwarded.append(f"{key}: {value}\r\n")
            forwarded.extend([
                f"Host: {self.host}:{self.port}\r\n",
                f"Origin: http://{self.host}:{self.port}\r\n",
                "Connection: Upgrade\r\n",
                "Upgrade: websocket\r\n",
                "\r\n",
            ])
            upstream.sendall("".join(forwarded).encode("latin-1"))
            upstream.settimeout(10)
            handshake = bytearray()
            while b"\r\n\r\n" not in handshake and len(handshake) < 65536:
                chunk = upstream.recv(4096)
                if not chunk:
                    raise OSError("Fermeture pendant la négociation WebSocket.")
                handshake.extend(chunk)
            if b"\r\n\r\n" not in handshake:
                raise OSError("Réponse WebSocket trop volumineuse.")
            handler.connection.sendall(handshake)
            if not handshake.startswith(b"HTTP/1.1 101"):
                return
            upstream.settimeout(None)
            handler.connection.settimeout(None)
            sockets = [handler.connection, upstream]
            while True:
                readable, _, exceptional = select.select(sockets, [], sockets, 60)
                if exceptional:
                    break
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    target = upstream if source is handler.connection else handler.connection
                    target.sendall(data)
        except (OSError, ValueError):
            # A disconnected browser simply ends its player connection.
            return
        finally:
            if upstream is not None:
                try:
                    upstream.close()
                except OSError:
                    pass

    def handle(self, handler: BaseHTTPRequestHandler) -> bool:
        """Handle one allow-listed media request; return False for other paths."""
        path, query = self._read_query(handler)
        if path.startswith("/media/"):
            parts = path.split("/")
            if len(parts) < 4 or parts[1] != "media":
                self._send_error(handler, 404, "Ressource média inconnue.")
                return True
            camera = parts[2]
            if not camera or len(camera) > 80 or not camera.isascii() or not all(ch.isalnum() or ch in "_.-" for ch in camera):
                self._send_error(handler, 400, "Identifiant de caméra invalide.")
                return True
            remainder = parts[3:]
            prefix = f"/media/{camera}"
            handler._media_prefix = prefix
            if remainder == ["stream.html"]:
                source = (query.get("src") or [camera])[0]
                if not self._valid_source(source, camera):
                    self._send_error(handler, 403, "Flux non autorisé.")
                    return True
                mode = (query.get("mode") or ["webrtc,mse,hls"])[0]
                if mode != "webrtc,mse,hls":
                    self._send_error(handler, 400, "Mode de lecture non autorisé.")
                    return True
                ticket = (query.get("ticket") or [""])[0]
                cookie_header = None
                if ticket:
                    try:
                        session = self._exchange_ticket(ticket, camera)
                    except MediaGatewayError as exc:
                        self._send_error(handler, 401, str(exc))
                        return True
                    cookie_name = self.COOKIE_PREFIX + camera
                    cookie_header = f"{cookie_name}={session}; Path=/; Max-Age={self.SESSION_TTL}; HttpOnly"
                    if handler.headers.get("X-Forwarded-Proto", "").lower() == "https":
                        cookie_header += "; SameSite=None; Secure"
                    else:
                        cookie_header += "; SameSite=Lax"
                    clean_query = urllib.parse.urlencode({"src": source, "mode": mode})
                    handler._media_clean_url = f"{prefix}/stream.html?{clean_query}"
                elif not self._same_origin_request(handler):
                    self._send_error(handler, 403, "Origine média non autorisée.")
                    return True
                if not ticket and camera not in self._cookie_sessions(handler):
                    self._send_error(handler, 401, "Session média absente ou expirée.")
                    return True
                upstream_path = "/stream.html?" + urllib.parse.urlencode({"src": source, "mode": mode})
                self._proxy_http(handler, upstream_path, cookie_header, rewrite_viewer=True)
                return True

            if not self._same_origin_request(handler):
                self._send_error(handler, 403, "Origine média non autorisée.")
                return True
            sessions = self._cookie_sessions(handler)
            if camera not in sessions:
                self._send_error(handler, 401, "Session média absente ou expirée.")
                return True
            if len(remainder) == 1 and remainder[0] in self.VIEWER_ASSETS:
                self._proxy_http(handler, "/" + remainder[0])
                return True
            if len(remainder) == 2 and remainder == ["api", "ws"]:
                source = (query.get("src") or [""])[0]
                if not self._valid_source(source, camera):
                    self._send_error(handler, 403, "Source WebSocket non autorisée.")
                    return True
                upstream_path = "/api/ws?" + urllib.parse.urlencode({"src": source})
                self._proxy_websocket(handler, upstream_path)
                return True
            if len(remainder) == 3 and remainder[:2] == ["api", "hls"]:
                suffix = remainder[2:]
                if len(suffix) != 1 or suffix[0] in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", suffix[0]):
                    self._send_error(handler, 404, "Ressource HLS non autorisée.")
                    return True
                upstream_path = "/api/hls/" + "/".join(suffix)
                if handler.path.find("?") >= 0:
                    upstream_path += "?" + handler.path.split("?", 1)[1]
                self._proxy_http(handler, upstream_path)
                return True
            self._send_error(handler, 404, "Ressource du lecteur non autorisée.")
            return True

        if path == "/api/ws":
            if not self._same_origin_request(handler):
                self._send_error(handler, 403, "Origine média non autorisée.")
                return True
            source = (query.get("src") or [""])[0]
            sessions = self._cookie_sessions(handler)
            camera = next((name for name in sessions if self._valid_source(source, name)), None)
            if camera is None:
                self._send_error(handler, 401, "Session média absente ou expirée.")
                return True
            upstream_path = "/api/ws?" + urllib.parse.urlencode({"src": source})
            self._proxy_websocket(handler, upstream_path)
            return True

        if path.startswith("/api/hls/"):
            if not self._same_origin_request(handler):
                self._send_error(handler, 403, "Origine média non autorisée.")
                return True
            sessions = self._cookie_sessions(handler)
            if not sessions:
                self._send_error(handler, 401, "Session média absente ou expirée.")
                return True
            # go2rtc HLS URLs are rooted at /api/hls/{src}/... . A valid
            # cookie alone is not sufficient: bind the source in the URL to
            # one of the camera sessions presented by this request.
            suffix = path[len("/api/hls/"):]
            parts = suffix.split("/")
            if (
                len(parts) < 2
                or any(
                    part in ("", ".", "..")
                    or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", part)
                    for part in parts
                )
            ):
                self._send_error(handler, 404, "Ressource HLS non autorisée.")
                return True
            source = parts[0]
            camera = next(
                (name for name in sessions if self._valid_source(source, name)),
                None,
            )
            if camera is None:
                self._send_error(handler, 403, "Source HLS non autorisée pour cette session.")
                return True
            upstream_path = path
            if handler.path.find("?") >= 0:
                upstream_path += "?" + handler.path.split("?", 1)[1]
            self._proxy_http(handler, upstream_path)
            return True
        return False
