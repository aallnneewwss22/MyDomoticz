"""In-memory coordination of shared per-camera transcoding sessions."""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

HEARTBEAT_INTERVAL_SECONDS = 10
SESSION_LEASE_SECONDS = 60
EXPIRATION_SWEEP_INTERVAL_SECONDS = 5
ALLOWED_RESOLUTIONS = {(1920, 1080), (1280, 720), (854, 480), (640, 360)}
ALLOWED_FPS = {15, 10, 5, 2, 1, 0.5, 0.2}
MIN_BITRATE_KBPS = 50
MAX_BITRATE_KBPS = 2000
LOGGER = logging.getLogger("go2rtc-control.sessions")


class SessionError(Exception):
    """Base error for invalid session operations."""


class SessionUnauthorized(SessionError):
    """The supplied session token does not match the session."""


class SessionConflict(SessionError):
    """An operation conflicts with the currently shared camera profile."""


class SessionUnavailable(SessionError):
    """The transcoder could not be started, stopped, or verified."""


def normalize_profile(profile: object) -> dict[str, object]:
    """Validate and normalize a user-requested transcode profile."""
    if not isinstance(profile, dict):
        raise SessionError("Le profil de transcodage doit être un objet.")
    expected = {"source", "width", "height", "fps", "bitrate_kbps"}
    if set(profile) != expected:
        raise SessionError("Le profil doit contenir source, width, height, fps et bitrate_kbps.")
    source = profile["source"]
    width, height = profile["width"], profile["height"]
    fps, bitrate = profile["fps"], profile["bitrate_kbps"]
    if source not in ("720p", "1080p"):
        raise SessionError("La source native doit être 720p ou 1080p.")
    if isinstance(width, bool) or not isinstance(width, int):
        raise SessionError("La largeur doit être un entier.")
    if isinstance(height, bool) or not isinstance(height, int):
        raise SessionError("La hauteur doit être un entier.")
    if (width, height) not in ALLOWED_RESOLUTIONS:
        raise SessionError("Résolution de sortie non autorisée.")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps not in ALLOWED_FPS:
        raise SessionError("Cadence IPS non autorisée.")
    if isinstance(bitrate, bool) or not isinstance(bitrate, int) or not MIN_BITRATE_KBPS <= bitrate <= MAX_BITRATE_KBPS:
        raise SessionError(f"Le débit cible doit être compris entre {MIN_BITRATE_KBPS} et {MAX_BITRATE_KBPS} kbit/s.")
    return {
        "source": source, "width": width, "height": height,
        "fps": float(fps), "bitrate_kbps": bitrate,
    }


class SessionManager:
    """Coordinate one shared transcode profile and many sessions per camera.

    Producer callbacks are injected by the future HTTP/go2rtc adapter. Importing
    this module never starts FFmpeg or changes the existing camera streams.
    """

    def __init__(
        self,
        start_producer: Callable[[str, dict[str, object]], bool],
        stop_producer: Callable[[str], None],
        producer_health: Callable[[str], bool],
        *,
        clock: Callable[[], float] = time.monotonic,
        lease_seconds: int = SESSION_LEASE_SECONDS,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds doit être positif")
        self._start_producer = start_producer
        self._stop_producer = stop_producer
        self._producer_health = producer_health
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._map_lock = threading.RLock()
        self._camera_locks: dict[str, threading.RLock] = {}
        self._cameras: dict[str, dict[str, object]] = {}
        self._closed = False
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None

    def _camera_lock(self, camera_id: str) -> threading.RLock:
        with self._map_lock:
            return self._camera_locks.setdefault(camera_id, threading.RLock())

    @contextmanager
    def camera_guard(self, camera_id: str) -> Iterator[None]:
        """Serialize compound operations for one logical camera."""
        if not isinstance(camera_id, str) or not camera_id or len(camera_id) > 80:
            raise SessionError("Identifiant logique de caméra invalide.")
        with self._camera_lock(camera_id):
            yield

    def _camera_state(self, camera_id: str) -> dict[str, object]:
        with self._map_lock:
            return self._cameras.setdefault(camera_id, {
                "state": "idle", "active_profile": None,
                "sessions": {}, "last_error": None,
            })

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _new_session(self, state: dict[str, object]) -> dict[str, str]:
        now = self._clock()
        session_id = secrets.token_urlsafe(18)
        token = secrets.token_urlsafe(32)
        sessions = state["sessions"]
        assert isinstance(sessions, dict)
        sessions[session_id] = {
            "token_hash": self._token_hash(token),
            "created_at": now, "last_heartbeat": now,
            "expires_at": now + self._lease_seconds,
        }
        return {"session_id": session_id, "session_token": token}

    def _stop_if_unused(self, camera_id: str, state: dict[str, object]) -> None:
        sessions = state["sessions"]
        assert isinstance(sessions, dict)
        if sessions:
            return
        if state["active_profile"] is None:
            state["state"] = "idle"
            return
        state["state"] = "stopping"
        try:
            self._stop_producer(camera_id)
        except Exception as exc:
            state["state"] = "error"
            state["last_error"] = "Arrêt du transcodeur impossible."
            raise SessionUnavailable(state["last_error"]) from exc
        state["active_profile"] = None
        state["state"] = "idle"
        state["last_error"] = None

    def acquire(self, camera_id: str, profile: object) -> dict[str, object]:
        normalized = normalize_profile(profile)
        with self.camera_guard(camera_id):
            if self._closed:
                raise SessionUnavailable("Le gestionnaire de sessions est arrêté.")
            state = self._camera_state(camera_id)
            sessions = state["sessions"]
            assert isinstance(sessions, dict)
            if sessions:
                active = state["active_profile"]
                if active != normalized:
                    return {
                        "result": "profile_conflict",
                        "requested_profile": normalized,
                        "active_profile": dict(active) if isinstance(active, dict) else None,
                    }
                try:
                    if not self._producer_health(camera_id):
                        state["state"] = "error"
                        state["last_error"] = "Le producteur de transcodage n'est plus actif."
                        raise SessionUnavailable(state["last_error"])
                except SessionUnavailable:
                    raise
                except Exception as exc:
                    state["state"] = "error"
                    state["last_error"] = "État du producteur indisponible."
                    raise SessionUnavailable(state["last_error"]) from exc
                credentials = self._new_session(state)
                state["state"] = "active"
                return {"result": "joined", **credentials, "expires_in": self._lease_seconds}
            if state["active_profile"] is not None or state["state"] in ("starting", "stopping", "error"):
                raise SessionUnavailable("L'état du transcodeur doit être réconcilié avant une nouvelle session.")
            state["state"] = "starting"
            state["active_profile"] = normalized
            try:
                ready = self._start_producer(camera_id, normalized)
                if ready is not True or not self._producer_health(camera_id):
                    raise SessionUnavailable("Le transcodeur n'a pas confirmé sa disponibilité.")
            except Exception as exc:
                # A failed start must not leave a phantom reservation. Ask the
                # producer adapter to clean up any partially created resource.
                try:
                    self._stop_producer(camera_id)
                except Exception as cleanup_exc:
                    state["state"] = "error"
                    state["last_error"] = "Démarrage et nettoyage du transcodeur impossibles."
                    raise SessionUnavailable(state["last_error"]) from cleanup_exc
                state["state"] = "idle"
                state["active_profile"] = None
                state["last_error"] = "Démarrage du transcodeur impossible."
                if isinstance(exc, SessionUnavailable):
                    raise
                raise SessionUnavailable(state["last_error"]) from exc
            credentials = self._new_session(state)
            state["state"] = "active"
            state["last_error"] = None
            return {"result": "started", **credentials, "expires_in": self._lease_seconds}

    def heartbeat(self, camera_id: str, session_id: str, token: str) -> dict[str, object]:
        with self.camera_guard(camera_id):
            state = self._camera_state(camera_id)
            sessions = state["sessions"]
            assert isinstance(sessions, dict)
            session = sessions.get(session_id)
            if not isinstance(session, dict):
                return {"result": "session_expired"}
            if not isinstance(token, str) or not secrets.compare_digest(
                str(session["token_hash"]), self._token_hash(token)
            ):
                raise SessionUnauthorized("Jeton de session invalide.")
            now = self._clock()
            if now >= float(session["expires_at"]):
                del sessions[session_id]
                self._stop_if_unused(camera_id, state)
                return {"result": "session_expired"}
            session["last_heartbeat"] = now
            session["expires_at"] = now + self._lease_seconds
            return {"result": "renewed", "expires_in": self._lease_seconds}

    def release(self, camera_id: str, session_id: str, token: str) -> dict[str, object]:
        with self.camera_guard(camera_id):
            state = self._camera_state(camera_id)
            sessions = state["sessions"]
            assert isinstance(sessions, dict)
            session = sessions.get(session_id)
            if not isinstance(session, dict):
                return {"result": "released", "session_count": len(sessions)}
            if not isinstance(token, str) or not secrets.compare_digest(
                str(session["token_hash"]), self._token_hash(token)
            ):
                raise SessionUnauthorized("Jeton de session invalide.")
            del sessions[session_id]
            self._stop_if_unused(camera_id, state)
            return {"result": "released", "session_count": len(sessions)}

    def cleanup_expired(self) -> list[dict[str, str]]:
        """Remove expired sessions; schedule this method every five seconds."""
        now = self._clock()
        with self._map_lock:
            camera_ids = list(self._cameras)
        expired: list[dict[str, str]] = []
        for camera_id in camera_ids:
            with self.camera_guard(camera_id):
                state = self._camera_state(camera_id)
                sessions = state["sessions"]
                assert isinstance(sessions, dict)
                for session_id, session in list(sessions.items()):
                    if now >= float(session["expires_at"]):
                        del sessions[session_id]
                        expired.append({"camera_id": camera_id, "session_id": session_id})
                self._stop_if_unused(camera_id, state)
        return expired

    def status(self, camera_id: str) -> dict[str, object]:
        with self.camera_guard(camera_id):
            state = self._camera_state(camera_id)
            sessions = state["sessions"]
            assert isinstance(sessions, dict)
            profile = state["active_profile"]
            return {
                "state": state["state"], "session_count": len(sessions),
                "active_profile": dict(profile) if isinstance(profile, dict) else None,
                "last_error": state["last_error"],
            }

    def health(self, camera_id: str) -> dict[str, object]:
        with self.camera_guard(camera_id):
            state = self._camera_state(camera_id)
            try:
                producer_active = bool(self._producer_health(camera_id))
            except Exception:
                producer_active = False
            return {
                "state": state["state"], "producer_active": producer_active,
                "session_count": len(state["sessions"]),
            }

    def assert_native_source_change_allowed(self, camera_id: str) -> None:
        """Raise while a transcode profile reserves the native camera source."""
        with self.camera_guard(camera_id):
            state = self._camera_state(camera_id)
            if (state["sessions"] or state["active_profile"] is not None
                    or state["state"] in ("starting", "stopping", "error")):
                raise SessionConflict("La modification de la source native est bloquée pendant le transcodage.")

    def assert_native_quality_change_allowed(self, camera_id: str) -> None:
        """Backward-compatible explicit guard for native resolution changes."""
        self.assert_native_source_change_allowed(camera_id)

    def start_reaper(self) -> None:
        """Start the five-second expiration sweep in a daemon thread."""
        with self._map_lock:
            if self._closed:
                raise SessionUnavailable("Le gestionnaire de sessions est arrêté.")
            if self._reaper_thread is not None and self._reaper_thread.is_alive():
                return
            self._reaper_stop.clear()
            self._reaper_thread = threading.Thread(
                target=self._reaper_loop, name="go2rtc-session-expirer", daemon=True,
            )
            self._reaper_thread.start()

    def _reaper_loop(self) -> None:
        while not self._reaper_stop.wait(EXPIRATION_SWEEP_INTERVAL_SECONDS):
            try:
                self.cleanup_expired()
            except Exception:
                LOGGER.exception("Échec du nettoyage des sessions de transcodage.")

    def close(self) -> None:
        """Stop the reaper and reject new acquisitions during service shutdown."""
        with self._map_lock:
            self._closed = True
            self._reaper_stop.set()
            thread = self._reaper_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=EXPIRATION_SWEEP_INTERVAL_SECONDS + 1)
