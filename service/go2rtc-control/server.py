#!/usr/bin/env python3
"""Authenticated local control API for go2rtc streams."""
from __future__ import annotations

import json
import logging
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
from session_manager import (
    SessionConflict, SessionError, SessionManager,
    SessionUnauthorized, SessionUnavailable,
)
from transcode_engine import FFmpegTranscodeEngine
from camera_profiles import (
    CameraProfileError, create_camera_profile, delete_camera_profile,
    normalize_camera_profiles, update_camera_profile, validate_selected_profile,
)

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
TRANSCODE_FFMPEG = os.environ.get("TRANSCODE_FFMPEG", "/usr/bin/ffmpeg")
TRANSCODE_RTSP_HOST = os.environ.get("TRANSCODE_RTSP_HOST", "127.0.0.1")
TRANSCODE_RTSP_PORT = int(os.environ.get("TRANSCODE_RTSP_PORT", "8554"))
REGISTRY_LOCK = threading.RLock()
LOGGER = logging.getLogger("go2rtc-control.ptz")
TRANSCODE_ENGINE = FFmpegTranscodeEngine(
    ffmpeg_bin=TRANSCODE_FFMPEG,
    rtsp_host=TRANSCODE_RTSP_HOST,
    rtsp_port=TRANSCODE_RTSP_PORT,
    go2rtc_api=GO2RTC_API,
)
TRANSCODE_ENGINE_AVAILABLE = TRANSCODE_ENGINE.available()

SESSION_MANAGER = SessionManager(
    TRANSCODE_ENGINE.start,
    TRANSCODE_ENGINE.stop,
    TRANSCODE_ENGINE.health,
)


PTZ_CACHE_LOCK = threading.RLock()
PTZ_CLIENT_CACHE: dict[tuple[str, int, str, str], tuple[object, str]] = {}


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
    """Initialize the private registry and migrate existing cameras to the profile model."""
    if not SOURCE_REGISTRY.exists():
        sources = load_go2rtc_sources()
        _write_registry_atomically(sources)
    migrate_camera_profiles()


def load_camera_settings() -> dict[str, dict[str, object]]:
    """Load private camera sources, shared audio/video preferences and ONVIF settings."""
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
            try:
                profiles, default_profile_id = normalize_camera_profiles(None, None, "1080p")
            except CameraProfileError as exc:
                raise ControlError(f"Profils vidéo invalides pour {name}: {exc}") from exc
            cameras[name] = {
                "source": entry.strip(), "audio_enabled": True, "quality": "1080p",
                "default_profile_id": default_profile_id, "profiles": profiles, "selected_profile_id": "native",
            }
        elif isinstance(entry, dict):
            source, audio_enabled = entry.get("source"), entry.get("audio_enabled", True)
            quality = entry.get("quality", "1080p")
            if quality not in ("720p", "1080p"):
                quality = "1080p"
            if isinstance(source, str) and source.strip() and isinstance(audio_enabled, bool):
                try:
                    profiles, default_profile_id = normalize_camera_profiles(
                        entry.get("profiles"), entry.get("default_profile_id"), quality,
                        enforce_native_limit=False,
                    )
                    selected_profile_id = validate_selected_profile(
                        profiles, entry.get("selected_profile_id")
                    )
                except CameraProfileError as exc:
                    raise ControlError(f"Profils vidéo invalides pour {name}: {exc}") from exc
                settings: dict[str, object] = {
                    "source": source.strip(), "audio_enabled": audio_enabled, "quality": quality,
                    "default_profile_id": default_profile_id, "profiles": profiles,
                    "selected_profile_id": selected_profile_id,
                }
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


def migrate_camera_profiles() -> None:
    """Persist the mandatory native profile for every supported legacy camera."""
    try:
        raw = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlError("Registre local des caméras illisible.") from exc
    if not isinstance(raw, dict):
        raise ControlError("Registre local des caméras invalide.")

    needs_migration = False
    for name, entry in raw.items():
        if not isinstance(name, str) or not STREAM_NAME.fullmatch(name):
            continue
        if isinstance(entry, str) and entry.strip():
            needs_migration = True
        elif isinstance(entry, dict):
            source = entry.get("source")
            audio_enabled = entry.get("audio_enabled", True)
            if (
                isinstance(source, str) and source.strip()
                and isinstance(audio_enabled, bool)
                and (
                    "profiles" not in entry
                    or not isinstance(entry.get("profiles"), dict)
                    or "native" not in entry.get("profiles", {})
                    or "default_profile_id" not in entry
                    or "selected_profile_id" not in entry
                )
            ):
                needs_migration = True

    # Validate existing profile data even when no migration is needed.
    cameras = load_camera_settings()
    if needs_migration:
        save_camera_settings(cameras)


def save_camera_settings(cameras: dict[str, dict[str, object]]) -> None:
    """Persist normalized camera settings atomically with private permissions."""
    normalized_cameras: dict[str, dict[str, object]] = {}
    for name, settings in cameras.items():
        if not isinstance(settings, dict):
            raise ControlError("Configuration de caméra invalide.")
        entry = dict(settings)
        quality = entry.get("quality", "1080p")
        try:
            profiles, default_profile_id = normalize_camera_profiles(
                entry.get("profiles"), entry.get("default_profile_id"), quality,
                enforce_native_limit=False,
            )
        except CameraProfileError as exc:
            raise ControlError(f"Profils vidéo invalides pour {name}: {exc}") from exc
        entry["profiles"] = profiles
        entry["default_profile_id"] = default_profile_id
        try:
            entry["selected_profile_id"] = validate_selected_profile(profiles, entry.get("selected_profile_id"))
        except CameraProfileError as exc:
            raise ControlError(f"Profil sélectionné invalide pour {name}: {exc}") from exc
        normalized_cameras[name] = entry

    SOURCE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".cameras-", dir=str(SOURCE_REGISTRY.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized_cameras, handle, ensure_ascii=False, indent=2)
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


def source_for_quality(source: str, quality: str) -> str:
    """Select the camera native RTSP stream without transcoding."""
    if quality not in ("720p", "1080p"):
        raise ControlError("Qualité vidéo invalide.")
    base, separator, fragment = source.partition("#")
    parsed = urllib.parse.urlsplit(base)
    if not re.search(r"/stream[12]$", parsed.path):
        if quality == "1080p":
            return source
        raise ControlError("Cette source RTSP ne permet pas de sélectionner 720p : son chemin doit se terminer par /stream1 ou /stream2.")
    stream_path = "/stream2" if quality == "720p" else "/stream1"
    selected = urllib.parse.urlunsplit(parsed._replace(path=re.sub(r"/stream[12]$", stream_path, parsed.path)))
    return selected + ("#" + fragment if separator else "")


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


def _ptz_cache_key(settings: dict[str, object]) -> tuple[str, int, str, str]:
    config = settings.get("ptz")
    if not isinstance(config, dict):
        raise ControlError("La connexion ONVIF de cette caméra n'est pas configurée.")
    return (
        str(config["host"]),
        int(config.get("port", 80)),
        str(config.get("username", "")),
        str(config.get("password", "")),
    )


def _ptz_invalidate_cache(settings: dict[str, object]) -> None:
    """Discard a potentially stale ONVIF session after a failed PTZ operation."""
    try:
        key = _ptz_cache_key(settings)
    except (ControlError, KeyError, TypeError, ValueError):
        return
    with PTZ_CACHE_LOCK:
        PTZ_CLIENT_CACHE.pop(key, None)


def _ptz_log_exception(operation: str, settings: dict[str, object], exc: Exception) -> None:
    """Log ONVIF diagnostics without ever exposing configured credentials."""
    config = settings.get("ptz")
    config = config if isinstance(config, dict) else {}
    host = str(config.get("host", "hôte inconnu"))
    detail = str(exc).replace(chr(13), " ").replace(chr(10), " ")
    for secret in (config.get("username"), config.get("password")):
        if isinstance(secret, str) and secret:
            detail = detail.replace(secret, "[masqué]")
    if not detail:
        detail = "(aucun détail fourni par la bibliothèque ONVIF)"
    LOGGER.warning(
        "Échec PTZ %s vers %s (%s) : %s",
        operation,
        host,
        type(exc).__name__,
        detail[:500],
    )


def _ptz_connection(settings: dict[str, object]):
    if ONVIFCamera is None:
        raise ControlError("La bibliothèque ONVIF n'est pas installée sur le Raspberry Pi.")
    key = _ptz_cache_key(settings)
    with PTZ_CACHE_LOCK:
        cached = PTZ_CLIENT_CACHE.get(key)
        if cached is not None:
            return cached
        try:
            camera = ONVIFCamera(key[0], key[1], key[2], key[3])
            media = camera.create_media_service()
            profiles = media.GetProfiles()
            profile = next((item for item in profiles if getattr(item, "PTZConfiguration", None)), None)
            if profile is None:
                raise ControlError("Aucun profil ONVIF avec capacités PTZ n'a été trouvé.")
            result = (camera.create_ptz_service(), profile.token)
            PTZ_CLIENT_CACHE[key] = result
            return result
        except ControlError:
            raise
        except Exception as exc:
            _ptz_log_exception("connexion", settings, exc)
            raise ControlError("Connexion ONVIF impossible. Consulte le journal go2rtc-control pour le détail technique.") from exc


def _ptz_float(value: object, name: str, minimum: float = -1.0, maximum: float = 1.0) -> float:
    try: number = float(value)
    except (TypeError, ValueError) as exc: raise ControlError("Valeur PTZ invalide : " + name + ".") from exc
    if not minimum <= number <= maximum: raise ControlError("Valeur PTZ hors limites : " + name + ".")
    return number


def ptz_move(settings: dict[str, object], payload: dict[str, object]) -> None:
    """Send one finite relative pan/tilt step; never rely on ContinuousMove."""
    pan = _ptz_float(payload.get("pan", 0), "pan")
    tilt = _ptz_float(payload.get("tilt", 0), "tilt")
    speed = _ptz_float(payload.get("speed", 0.5), "speed", 0.05, 1.0)
    if abs(pan) < 0.001 and abs(tilt) < 0.001:
        raise ControlError("Le déplacement demandé est nul.")
    ptz, profile_token = _ptz_connection(settings)
    # Pan/Tilt already contains the browser-selected GainPTZ. Values remain
    # normalized to the camera's GenericTranslation space (-1..1).
    # The browser sends another finite step only while the joystick is deflected.
    try:
        request = ptz.create_type("RelativeMove")
        request.ProfileToken = profile_token
        request.Translation = {"PanTilt": {"x": pan, "y": tilt}}
        request.Speed = {"PanTilt": {"x": speed, "y": speed}}
        ptz.RelativeMove(request)
    except Exception as exc:
        _ptz_invalidate_cache(settings)
        _ptz_log_exception("RelativeMove", settings, exc)
        raise ControlError("La commande de déplacement relatif PTZ a échoué. Consulte le journal go2rtc-control pour le détail technique.") from exc


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


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    try: length = int(handler.headers.get("Content-Length", "0"))
    except ValueError: length = 0
    if length <= 0 or length > 4096: raise ControlError("Corps JSON absent ou trop volumineux.")
    try: payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ControlError("Corps JSON invalide.") from exc
    if not isinstance(payload, dict): raise ControlError("Le corps JSON doit être un objet.")
    return payload

class Handler(BaseHTTPRequestHandler):
    server_version = "go2rtc-control/1.5"

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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
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
            with SESSION_MANAGER.camera_guard(name), REGISTRY_LOCK:
                cameras = load_camera_settings()
                if name not in cameras:
                    self.send_json(404, {"error": "Caméra absente du registre local."})
                    return
                settings = cameras[name]
                source = str(settings["source"])
                audio_enabled = bool(settings["audio_enabled"])
                quality = str(settings.get("quality", "1080p"))
                if action == "status":
                    self.send_json(200, {"enabled": stream_exists(name), "audio_enabled": audio_enabled, "quality": quality})
                    return
                if action == "stop":
                    SESSION_MANAGER.assert_native_source_change_allowed(name)
                    # DELETE also removes the YAML stream definition. The private
                    # registry remains the source of truth for the next start.
                    status, _ = go2rtc_request("DELETE", "/api/streams?" + urllib.parse.urlencode({"src": name}))
                    if status not in (200, 204, 404):
                        raise ControlError(f"Arrêt refusé par go2rtc (HTTP {status}).")
                    self.send_json(200, {"enabled": False, "audio_enabled": audio_enabled, "quality": quality})
                    return
                if action == "start":
                    SESSION_MANAGER.assert_native_source_change_allowed(name)
                    replace_stream_source(name, source_for_audio(source_for_quality(source, quality), audio_enabled))
                    self.send_json(200, {"enabled": True, "audio_enabled": audio_enabled, "quality": quality})
                    return
                if action == "quality":
                    payload = _read_json_body(self)
                    next_quality = payload.get("quality")
                    if next_quality not in ("720p", "1080p"):
                        raise ControlError("Le champ quality doit valoir 720p ou 1080p.")
                    selected_source = source_for_quality(source, next_quality)
                    if next_quality != quality:
                        SESSION_MANAGER.assert_native_source_change_allowed(name)
                        running = stream_exists(name)
                        if running:
                            replace_stream_source(name, source_for_audio(selected_source, audio_enabled))
                        if next_quality == "720p":
                            profiles = settings.get("profiles")
                            selected_id = settings.get("selected_profile_id", "native")
                            selected_profile = profiles.get(selected_id) if isinstance(profiles, dict) else None
                            if (
                                isinstance(selected_profile, dict)
                                and (
                                    int(selected_profile.get("width", 0)) > 1280
                                    or int(selected_profile.get("height", 0)) > 720
                                )
                            ):
                                # Keep the custom profile saved, but use the native
                                # stream until the camera is switched back to 1080p.
                                settings["selected_profile_id"] = "native"
                        settings["quality"] = next_quality
                        save_camera_settings(cameras)
                    self.send_json(200, {"enabled": stream_exists(name), "audio_enabled": audio_enabled, "quality": next_quality})
                    return
                if action == "audio":
                    payload = _read_json_body(self)
                    if not isinstance(payload.get("enabled"), bool):
                        raise ControlError("Le champ enabled doit être un booléen.")
                    next_audio = payload["enabled"]
                    if next_audio != audio_enabled:
                        SESSION_MANAGER.assert_native_source_change_allowed(name)
                        running = stream_exists(name)
                        if running:
                            replace_stream_source(name, source_for_audio(source_for_quality(source, quality), next_audio))
                        settings["audio_enabled"] = next_audio
                        save_camera_settings(cameras)
                    self.send_json(200, {"enabled": stream_exists(name), "audio_enabled": next_audio, "quality": quality})
                    return
                if action == "ptz-status":
                    ptz = settings.get("ptz")
                    self.send_json(200, {"configured": isinstance(ptz, dict), "host": ptz.get("host", "") if isinstance(ptz, dict) else "", "port": ptz.get("port", 80) if isinstance(ptz, dict) else 80})
                    return
                if action == "ptz-config":
                    payload = _read_json_body(self)
                    host, port = payload.get("host"), payload.get("port", 80)
                    username, password = payload.get("username", ""), payload.get("password", "")
                    if not isinstance(host, str) or not host.strip() or len(host.strip()) > 253 or any(char in host for char in "/?#@ \\t\\r\\n"):
                        raise ControlError("Adresse IP ou nom d’hôte ONVIF invalide.")
                    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
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
                self.send_json(404, {"error": "Action inconnue."})
        except SessionConflict as exc:
            self.send_json(409, {"error": str(exc), "result": "blocked"})
        except ControlError as exc:
            self.send_json(502, {"error": str(exc)})

    def handle_profiles(self) -> None:
        """Authenticated CRUD API for one camera's stored video profiles."""
        if not self.authorized():
            return
        parts = urllib.parse.urlsplit(self.path).path.strip("/").split("/")
        if len(parts) not in (4, 5) or parts[:2] != ["api", "cameras"] or parts[3] != "profiles":
            self.send_json(404, {"error": "Route de profils inconnue."})
            return
        camera_id = urllib.parse.unquote(parts[2])
        if not STREAM_NAME.fullmatch(camera_id):
            self.send_json(400, {"error": "Nom de flux invalide."})
            return
        profile_id = urllib.parse.unquote(parts[4]) if len(parts) == 5 else None
        try:
            with SESSION_MANAGER.camera_guard(camera_id), REGISTRY_LOCK:
                cameras = load_camera_settings()
                if camera_id not in cameras:
                    self.send_json(404, {"error": "Caméra absente du registre local."})
                    return
                settings = cameras[camera_id]
                profiles = dict(settings["profiles"])
                quality = settings["quality"]
                selected = settings.get("selected_profile_id", "native")
                if self.command == "GET" and profile_id is None:
                    self.send_json(200, {"camera_id": camera_id, "selected_profile_id": selected,
                        "default_profile_id": "native", "profiles": list(profiles.values())})
                    return
                if self.command == "POST" and profile_id is None:
                    updated, new_id = create_camera_profile(profiles, quality, _read_json_body(self))
                    settings["profiles"] = updated
                    save_camera_settings(cameras)
                    self.send_json(201, {"profile": updated[new_id]})
                    return
                if self.command == "PUT" and profile_id == "selected":
                    payload = _read_json_body(self)
                    settings["selected_profile_id"] = validate_selected_profile(profiles, payload.get("profile_id"))
                    save_camera_settings(cameras)
                    self.send_json(200, {"selected_profile_id": settings["selected_profile_id"]})
                    return
                if self.command == "PUT" and profile_id:
                    updated = update_camera_profile(profiles, quality, profile_id, _read_json_body(self))
                    settings["profiles"] = updated
                    save_camera_settings(cameras)
                    self.send_json(200, {"profile": updated[profile_id]})
                    return
                if self.command == "DELETE" and profile_id:
                    updated = delete_camera_profile(profiles, profile_id)
                    settings["profiles"] = updated
                    if selected == profile_id:
                        settings["selected_profile_id"] = "native"
                    save_camera_settings(cameras)
                    self.send_json(200, {"deleted": profile_id,
                        "selected_profile_id": settings["selected_profile_id"]})
                    return
                self.send_json(405, {"error": "Méthode ou ressource de profil non autorisée."})
        except CameraProfileError as exc:
            self.send_json(400, {"error": str(exc)})
        except SessionConflict as exc:
            self.send_json(409, {"error": str(exc), "result": "blocked"})
        except ControlError as exc:
            self.send_json(502, {"error": str(exc)})

    def handle_transcode(self, action: str) -> None:
        if not self.authorized():
            return
        parts = urllib.parse.urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 5 or parts[:2] != ["api", "cameras"] or parts[3] != "transcode" or parts[4] != action:
            self.send_json(404, {"error": "Route de transcodage inconnue."})
            return
        camera_id = urllib.parse.unquote(parts[2])
        if not STREAM_NAME.fullmatch(camera_id):
            self.send_json(400, {"error": "Identifiant logique de caméra invalide."})
            return
        expected_method = "GET" if action in ("status", "health") else "POST"
        if self.command != expected_method:
            self.send_json(405, {"error": "Méthode HTTP non autorisée."})
            return
        try:
            # Use the existing logical camera ID from cameras.json. Keep the
            # per-camera lock while reading its native quality and changing
            # session state, so quality changes cannot race an acquire.
            with SESSION_MANAGER.camera_guard(camera_id):
                with REGISTRY_LOCK:
                    cameras = load_camera_settings()
                    if camera_id not in cameras:
                        self.send_json(404, {"error": "Caméra absente du registre local."})
                        return
                    native_quality = str(cameras[camera_id].get("quality", "1080p"))

                if action == "acquire":
                    payload = _read_json_body(self)
                    profile = payload.get("profile")
                    if not isinstance(profile, dict):
                        raise SessionError("Le champ profile doit être un objet.")
                    if profile.get("source") != native_quality:
                        self.send_json(409, {
                            "result": "native_quality_mismatch",
                            "requested_source": profile.get("source"),
                            "native_quality": native_quality,
                            "error": "Le profil doit utiliser la résolution native actuellement sélectionnée.",
                        })
                        return
                    result = SESSION_MANAGER.acquire(camera_id, profile)
                    if result.get("result") == "profile_conflict":
                        self.send_json(409, result)
                    else:
                        self.send_json(200, result)
                    return

                if action in ("heartbeat", "release"):
                    payload = _read_json_body(self)
                    session_id, token = payload.get("session_id"), payload.get("session_token")
                    if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
                        raise SessionError("Identifiant de session invalide.")
                    if not isinstance(token, str) or not token or len(token) > 256:
                        raise SessionError("Jeton de session invalide.")
                    if action == "heartbeat":
                        result = SESSION_MANAGER.heartbeat(camera_id, session_id, token)
                        self.send_json(410 if result.get("result") == "session_expired" else 200, result)
                    else:
                        self.send_json(200, SESSION_MANAGER.release(camera_id, session_id, token))
                    return

                if action == "status":
                    result = SESSION_MANAGER.status(camera_id)
                    result["engine_available"] = TRANSCODE_ENGINE_AVAILABLE
                    self.send_json(200, result)
                    return

                if action == "health":
                    result = SESSION_MANAGER.health(camera_id)
                    result["engine_available"] = TRANSCODE_ENGINE_AVAILABLE
                    self.send_json(200, result)
                    return

                self.send_json(404, {"error": "Action de transcodage inconnue."})
        except SessionUnauthorized as exc:
            self.send_json(401, {"error": str(exc)})
        except SessionConflict as exc:
            self.send_json(409, {"error": str(exc), "result": "blocked"})
        except SessionUnavailable as exc:
            self.send_json(503, {"error": str(exc), "result": "error"})
        except SessionError as exc:
            self.send_json(400, {"error": str(exc)})
        except ControlError as exc:
            self.send_json(502, {"error": str(exc)})

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path.startswith("/api/cameras/") and "/profiles" in path:
            self.handle_profiles()
            return
        parts = urllib.parse.urlsplit(self.path).path.rstrip("/").split("/")
        if len(parts) == 6 and parts[:2] == ["", "api"] and parts[4] == "transcode":
            self.handle_transcode(parts[5])
            return
        action = parts[-1]
        if action not in ("status", "ptz-status", "ptz-presets"):
            action = "status"
        self.handle_camera(action)

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path.startswith("/api/cameras/") and "/profiles" in path:
            self.handle_profiles()
            return
        parts = urllib.parse.urlsplit(self.path).path.rstrip("/").split("/")
        if len(parts) == 6 and parts[:2] == ["", "api"] and parts[4] == "transcode":
            self.handle_transcode(parts[5])
            return
        action = parts[-1]
        self.handle_camera(action)
 
    def do_PUT(self) -> None:
        self.handle_profiles()

    def do_DELETE(self) -> None:
        self.handle_profiles()


if __name__ == "__main__":
    read_token()
    ensure_source_registry()
    SESSION_MANAGER.start_reaper()
    server = ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        SESSION_MANAGER.close()
        TRANSCODE_ENGINE.close()
