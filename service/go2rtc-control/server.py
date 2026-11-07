#!/usr/bin/env python3
"""Authenticated local control API for go2rtc streams."""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from onvif import ONVIFCamera
except ImportError:
    ONVIFCamera = None

STREAM_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
GO2RTC_API = os.environ.get("GO2RTC_API", "http://127.0.0.1:1984").rstrip("/")
GO2RTC_CONFIG = Path(os.environ.get("GO2RTC_CONFIG", "/home/pi/go2rtc-test/go2rtc.yaml"))
SOURCE_REGISTRY = Path(os.environ.get("SOURCE_REGISTRY", "/var/lib/go2rtc-control/cameras.json"))
TOKEN_FILE = Path(os.environ.get("TOKEN_FILE", "/etc/go2rtc-control/token"))
DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://192.168.1.21:8080").rstrip("/")
CONTROL_HOST = os.environ.get("CONTROL_HOST", "0.0.0.0")
CONTROL_PORT = int(os.environ.get("CONTROL_PORT", "1985"))
REGISTRY_LOCK = threading.RLock()


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


def load_camera_settings() -> dict[str, dict[str, object]]:
    """Load private camera sources, shared audio preferences and ONVIF settings."""
    try:
        data = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlError("Registre local des caméras illisible.") from exc
    if not isinstance(data, dict):
        raise ControlError("Registre local des caméras invalide.")
    cameras: dict[str, dict[str, object]] = {}
    for name, entry in data.items():
        if not isinstance(name, str) or not STREAM_NAME.fullmatch(name): continue
        if isinstance(entry, str) and entry.strip():
            cameras[name] = {"source": entry.strip(), "audio_enabled": True}
        elif isinstance(entry, dict):
            source, audio_enabled = entry.get("source"), entry.get("audio_enabled", True)
            if isinstance(source, str) and source.strip() and isinstance(audio_enabled, bool):
                settings: dict[str, object] = {"source": source.strip(), "audio_enabled": audio_enabled}
                ptz = entry.get("ptz")
                if isinstance(ptz, dict):
                    host, port = ptz.get("host"), ptz.get("port", 80)
                    username, password = ptz.get("username", ""), ptz.get("password", "")
                    if isinstance(host, str) and host.strip() and isinstance(port, int) and 1 <= port <= 65535 and isinstance(username, str) and isinstance(password, str):
                        settings["ptz"] = {"host": host.strip(), "port": port, "username": username, "password": password}
                cameras[name] = settings
    return cameras

def load_sources() -> dict[str, str]:
    """Compatibility helper returning only the original source strings."""
    return {name: str(settings["source"]) for name, settings in load_camera_settings().items()}


def save_camera_settings(cameras: dict[str, dict[str, object]]) -> None:
    """Persist camera sources and audio preferences atomically with private permissions."""
    SOURCE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".cameras-", dir=str(SOURCE_REGISTRY.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cameras, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, SOURCE_REGISTRY)
        os.chmod(SOURCE_REGISTRY, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def source_for_audio(source: str, audio_enabled: bool) -> str:
    """Ask go2rtc for video only when audio is disabled."""
    if audio_enabled:
        return source
    base, separator, fragment = source.partition("#")
    if not separator:
        return source + "#media=video"
    options = [part for part in fragment.split("&") if part and not part.startswith("media=")]
    options.append("media=video")
    return base + "#" + "&".join(options)


def replace_stream_source(name: str, source: str) -> None:
    """Replace the one named stream, closing its old RTSP session first."""
    status, _ = go2rtc_request("DELETE", "/api/streams?" + urllib.parse.urlencode({"src": name}))
    if status not in (200, 204, 404):
        raise ControlError(f"Arrêt du flux refusé par go2rtc (HTTP {status}).")
    query = urllib.parse.urlencode({"name": name, "src": source})
    status, _ = go2rtc_request("PUT", "/api/streams?" + query)
    if status not in (200, 201, 204):
        raise ControlError(f"Création du flux refusée par go2rtc (HTTP {status}).")


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


def _ptz_connection(settings: dict[str, object]):
    if ONVIFCamera is None: raise ControlError("La bibliothèque ONVIF n'est pas installée sur le Raspberry Pi.")
    config = settings.get("ptz")
    if not isinstance(config, dict): raise ControlError("La connexion ONVIF de cette caméra n'est pas configurée.")
    try:
        camera = ONVIFCamera(str(config["host"]), int(config.get("port", 80)), str(config.get("username", "")), str(config.get("password", "")))
        media = camera.create_media_service()
        profiles = media.GetProfiles()
        profile = next((item for item in profiles if getattr(item, "PTZConfiguration", None)), None)
        if profile is None: raise ControlError("Aucun profil ONVIF avec capacités PTZ n'a été trouvé.")
        return camera.create_ptz_service(), profile.token
    except ControlError: raise
    except Exception as exc: raise ControlError("Connexion ONVIF impossible. Vérifie l'adresse, le port et les identifiants.") from exc


def _ptz_float(value: object, name: str, minimum: float = -1.0, maximum: float = 1.0) -> float:
    try: number = float(value)
    except (TypeError, ValueError) as exc: raise ControlError("Valeur PTZ invalide : " + name + ".") from exc
    if not minimum <= number <= maximum: raise ControlError("Valeur PTZ hors limites : " + name + ".")
    return number


def ptz_move(settings: dict[str, object], payload: dict[str, object]) -> None:
    ptz, profile_token = _ptz_connection(settings)
    pan, tilt, zoom = _ptz_float(payload.get("pan", 0), "pan"), _ptz_float(payload.get("tilt", 0), "tilt"), _ptz_float(payload.get("zoom", 0), "zoom")
    speed = _ptz_float(payload.get("speed", 0.5), "speed", 0.05, 1.0)
    try:
        request = ptz.create_type("ContinuousMove")
        request.ProfileToken = profile_token
        request.Velocity = {"PanTilt": {"x": pan * speed, "y": tilt * speed}, "Zoom": {"x": zoom * speed}}
        request.Timeout = "PT1S"
        ptz.ContinuousMove(request)
    except Exception as exc: raise ControlError("La commande de déplacement PTZ a échoué.") from exc


def ptz_stop(settings: dict[str, object]) -> None:
    ptz, profile_token = _ptz_connection(settings)
    try:
        request = ptz.create_type("Stop")
        request.ProfileToken, request.PanTilt, request.Zoom = profile_token, True, True
        ptz.Stop(request)
    except Exception as exc: raise ControlError("L'arrêt du mouvement PTZ a échoué.") from exc


def ptz_list_presets(settings: dict[str, object]) -> list[dict[str, str]]:
    ptz, profile_token = _ptz_connection(settings)
    try:
        presets = ptz.GetPresets({"ProfileToken": profile_token})
        return [{"token": str(item.token), "name": str(getattr(item, "Name", "") or item.token)} for item in (presets or []) if getattr(item, "token", None)]
    except Exception as exc: raise ControlError("Impossible de lire les positions prédéfinies ONVIF.") from exc


def ptz_goto_preset(settings: dict[str, object], token: str) -> None:
    if not token or len(token) > 128: raise ControlError("Identifiant de position prédéfinie invalide.")
    ptz, profile_token = _ptz_connection(settings)
    try:
        valid_tokens = {item["token"] for item in ptz_list_presets(settings)}
        if token not in valid_tokens: raise ControlError("Cette position prédéfinie n'existe plus sur la caméra.")
        ptz.GotoPreset({"ProfileToken": profile_token, "PresetToken": token})
    except ControlError: raise
    except Exception as exc: raise ControlError("Le déplacement vers cette position a échoué.") from exc


def ptz_save_preset(settings: dict[str, object], name: str) -> dict[str, str]:
    clean_name = " ".join(name.split()).strip()
    if not clean_name or len(clean_name) > 40: raise ControlError("Le nom de la position doit contenir entre 1 et 40 caractères.")
    ptz, profile_token = _ptz_connection(settings)
    try:
        token = ptz.SetPreset({"ProfileToken": profile_token, "PresetName": clean_name})
        return {"token": str(token), "name": clean_name}
    except Exception as exc: raise ControlError("Impossible d'enregistrer cette position sur la caméra.") from exc


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    try: length = int(handler.headers.get("Content-Length", "0"))
    except ValueError: length = 0
    if length <= 0 or length > 4096: raise ControlError("Corps JSON absent ou trop volumineux.")
    try: payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ControlError("Corps JSON invalide.") from exc
    if not isinstance(payload, dict): raise ControlError("Le corps JSON doit être un objet.")
    return payload

class Handler(BaseHTTPRequestHandler):
    server_version = "go2rtc-control/1.3"

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
            with REGISTRY_LOCK:
                cameras = load_camera_settings()
                if name not in cameras:
                    self.send_json(404, {"error": "Caméra absente du registre local."})
                    return
                settings = cameras[name]
                source = str(settings["source"])
                audio_enabled = bool(settings["audio_enabled"])
                if action == "status":
                    self.send_json(200, {"enabled": stream_exists(name), "audio_enabled": audio_enabled})
                    return
                if action == "stop":
                    # DELETE also removes the YAML stream definition. The private
                    # registry remains the source of truth for the next start.
                    status, _ = go2rtc_request("DELETE", "/api/streams?" + urllib.parse.urlencode({"src": name}))
                    if status not in (200, 204, 404):
                        raise ControlError(f"Arrêt refusé par go2rtc (HTTP {status}).")
                    self.send_json(200, {"enabled": False, "audio_enabled": audio_enabled})
                    return
                if action == "start":
                    replace_stream_source(name, source_for_audio(source, audio_enabled))
                    self.send_json(200, {"enabled": True, "audio_enabled": audio_enabled})
                    return
                if action == "audio":
                    payload = _read_json_body(self)
                    if not isinstance(payload.get("enabled"), bool):
                        raise ControlError("Le champ enabled doit être un booléen.")
                    next_audio = payload["enabled"]
                    if next_audio != audio_enabled:
                        running = stream_exists(name)
                        if running:
                            replace_stream_source(name, source_for_audio(source, next_audio))
                        settings["audio_enabled"] = next_audio
                        save_camera_settings(cameras)
                    self.send_json(200, {"enabled": stream_exists(name), "audio_enabled": next_audio})
                    return
                if action == "ptz-status":
                    ptz = settings.get("ptz")
                    self.send_json(200, {"configured": isinstance(ptz, dict), "host": ptz.get("host", "") if isinstance(ptz, dict) else "", "port": ptz.get("port", 80) if isinstance(ptz, dict) else 80})
                    return
                if action == "ptz-config":
                    payload = _read_json_body(self)
                    host, port = payload.get("host"), payload.get("port", 80)
                    username, password = payload.get("username", ""), payload.get("password", "")
                    if not isinstance(host, str) or not host.strip() or len(host.strip()) > 253:
                        raise ControlError("Adresse IP ou nom d’hôte ONVIF invalide.")
                    if not isinstance(port, int) or not 1 <= port <= 65535:
                        raise ControlError("Port ONVIF invalide.")
                    if not isinstance(username, str) or not isinstance(password, str):
                        raise ControlError("Identifiants ONVIF invalides.")
                    previous = settings.get("ptz", {})
                    if not username and isinstance(previous, dict): username = str(previous.get("username", ""))
                    if not password and isinstance(previous, dict): password = str(previous.get("password", ""))
                    settings["ptz"] = {"host": host.strip(), "port": port, "username": username, "password": password}
                    save_camera_settings(cameras)
                    self.send_json(200, {"configured": True, "host": host.strip(), "port": port})
                    return
                if action == "ptz-move":
                    ptz_move(settings, _read_json_body(self))
                    self.send_json(200, {"ok": True})
                    return
                if action == "ptz-stop":
                    ptz_stop(settings)
                    self.send_json(200, {"ok": True})
                    return
                if action == "ptz-presets":
                    self.send_json(200, {"presets": ptz_list_presets(settings)})
                    return
                if action == "ptz-goto":
                    payload = _read_json_body(self)
                    token = payload.get("token")
                    if not isinstance(token, str): raise ControlError("Identifiant de position prédéfinie invalide.")
                    ptz_goto_preset(settings, token)
                    self.send_json(200, {"ok": True})
                    return
                if action == "ptz-save-preset":
                    payload = _read_json_body(self)
                    preset_name = payload.get("name")
                    if not isinstance(preset_name, str): raise ControlError("Nom de position prédéfinie invalide.")
                    self.send_json(200, {"preset": ptz_save_preset(settings, preset_name)})
                    return
                self.send_json(404, {"error": "Action inconnue."})
        except ControlError as exc:
            self.send_json(502, {"error": str(exc)})
    def do_GET(self) -> None:
        action = urllib.parse.urlsplit(self.path).path.rstrip("/").split("/")[-1]
        if action not in ("status", "ptz-status", "ptz-presets"):
            action = "status"
        self.handle_camera(action)

    def do_POST(self) -> None:
        action = urllib.parse.urlsplit(self.path).path.rstrip("/").split("/")[-1]
        self.handle_camera(action)


if __name__ == "__main__":
    read_token()
    ensure_source_registry()
    ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), Handler).serve_forever()
