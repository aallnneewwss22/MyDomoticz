"""Versioned, server-side backups for the complete per-camera registry.

The module deliberately returns only metadata from previews. Camera sources and
ONVIF credentials remain on the Raspberry Pi and are never sent to the browser.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from camera_profiles import (
    CameraProfileError,
    normalize_camera_profiles,
    validate_selected_profile,
)

CAMERA_BACKUP_FORMAT = "mydomoticz-camera-settings"
CAMERA_BACKUP_VERSION = 1
CAMERA_BACKUP_MAX_BYTES = 4 * 1024 * 1024
CAMERA_BACKUP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,57}\.json$")
CAMERA_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

FIELD_LABELS = {
    "source": "source RTSP",
    "quality": "résolution native",
    "audio_enabled": "préférence audio",
    "ptz": "connexion ONVIF",
    "profiles": "profils vidéo locaux",
    "default_profile_id": "profil par défaut",
    "selected_profile_id": "profil sélectionné",
    "ptz_upside_down": "orientation PTZ",
}


class CameraBackupError(ValueError):
    """A camera backup is malformed or unsupported."""


def backup_path(directory: Path, name: str) -> Path:
    if not isinstance(name, str) or not CAMERA_BACKUP_NAME.fullmatch(name):
        raise CameraBackupError("Nom de sauvegarde caméra invalide.")
    if name in {".", ".."}:
        raise CameraBackupError("Nom de sauvegarde caméra invalide.")
    return directory / name


def ensure_backup_directory(directory: Path) -> None:
    if directory.is_symlink():
        raise OSError("Le répertoire de sauvegardes caméra ne peut pas être un lien symbolique.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)


def _normalize_cameras(raw: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise CameraBackupError("La liste des caméras dans la sauvegarde est invalide.")
    if len(raw) > 100:
        raise CameraBackupError("La sauvegarde contient trop de caméras.")

    normalized: dict[str, dict[str, Any]] = {}
    for camera_id, value in raw.items():
        if not isinstance(camera_id, str) or not CAMERA_ID.fullmatch(camera_id):
            raise CameraBackupError("Identifiant de caméra invalide.")
        if not isinstance(value, dict):
            raise CameraBackupError("Configuration de caméra invalide.")

        allowed = {
            "source", "quality", "audio_enabled", "ptz", "profiles",
            "default_profile_id", "selected_profile_id", "ptz_upside_down",
        }
        if set(value) - allowed:
            raise CameraBackupError("La configuration contient des champs caméra inconnus.")
        source = value.get("source")
        quality = value.get("quality", "1080p")
        audio_enabled = value.get("audio_enabled", True)
        if not isinstance(source, str) or not source.strip() or len(source) > 4096:
            raise CameraBackupError("Source RTSP invalide.")
        if quality not in ("720p", "1080p") or not isinstance(audio_enabled, bool):
            raise CameraBackupError("Paramètres audio/vidéo invalides.")

        try:
            profiles, default_profile_id = normalize_camera_profiles(
                value.get("profiles"), value.get("default_profile_id"), quality,
                enforce_native_limit=False,
            )
            selected_profile_id = validate_selected_profile(
                profiles, value.get("selected_profile_id", "native")
            )
        except CameraProfileError as exc:
            raise CameraBackupError("Profils vidéo invalides dans la sauvegarde.") from exc
        selected_profile = profiles.get(selected_profile_id)
        if (
            quality == "720p" and selected_profile_id != "native"
            and isinstance(selected_profile, dict)
            and (selected_profile.get("width", 0) > 1280 or selected_profile.get("height", 0) > 720)
        ):
            raise CameraBackupError("Le profil sélectionné dépasse la résolution native sauvegardée.")

        item: dict[str, Any] = {
            "source": source.strip(),
            "quality": quality,
            "audio_enabled": audio_enabled,
            "profiles": profiles,
            "default_profile_id": default_profile_id,
            "selected_profile_id": selected_profile_id,
            "ptz_upside_down": value.get("ptz_upside_down", False),
        }
        if not isinstance(item["ptz_upside_down"], bool):
            raise CameraBackupError("Orientation PTZ invalide.")

        ptz = value.get("ptz")
        if ptz is not None:
            if not isinstance(ptz, dict) or set(ptz) != {"host", "port", "username", "password"}:
                raise CameraBackupError("Configuration ONVIF invalide.")
            host, port = ptz["host"], ptz["port"]
            username, password = ptz["username"], ptz["password"]
            if (
                not isinstance(host, str) or not host.strip() or len(host) > 253
                or any(char in host for char in "/?#@ \\t\\r\\n")
                or isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
                or not isinstance(username, str) or len(username) > 1024
                or not isinstance(password, str) or len(password) > 4096
            ):
                raise CameraBackupError("Configuration ONVIF invalide.")
            item["ptz"] = {
                "host": host.strip(), "port": port,
                "username": username, "password": password,
            }
        normalized[camera_id] = item
    return normalized


def make_backup(cameras: dict[str, dict[str, object]], *, created_at: Optional[str] = None) -> dict[str, object]:
    normalized = _normalize_cameras(cameras)
    return {
        "format": CAMERA_BACKUP_FORMAT,
        "version": CAMERA_BACKUP_VERSION,
        "createdAt": created_at or datetime.now(timezone.utc).isoformat(),
        "cameras": normalized,
    }


def validate_backup(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise CameraBackupError("Fichier de sauvegarde caméra invalide.")
    if payload.get("format") != CAMERA_BACKUP_FORMAT or payload.get("version") != CAMERA_BACKUP_VERSION:
        raise CameraBackupError("Format ou version de sauvegarde caméra non pris en charge.")
    if set(payload) != {"format", "version", "createdAt", "cameras"}:
        raise CameraBackupError("Structure de sauvegarde caméra invalide.")
    created_at = payload.get("createdAt")
    if not isinstance(created_at, str) or len(created_at) > 64:
        raise CameraBackupError("Date de sauvegarde invalide.")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CameraBackupError("Date de sauvegarde invalide.") from exc
    cameras = _normalize_cameras(payload.get("cameras"))
    validated = {
        "format": CAMERA_BACKUP_FORMAT,
        "version": CAMERA_BACKUP_VERSION,
        "createdAt": created_at,
        "cameras": cameras,
    }
    encoded = json.dumps(validated, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > CAMERA_BACKUP_MAX_BYTES:
        raise CameraBackupError("Fichier de sauvegarde caméra trop volumineux.")
    return validated


def write_backup(directory: Path, name: str, payload: object) -> None:
    validated = validate_backup(payload)
    path = backup_path(directory, name)
    encoded = json.dumps(validated, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) > CAMERA_BACKUP_MAX_BYTES:
        raise CameraBackupError("Fichier de sauvegarde caméra trop volumineux.")
    ensure_backup_directory(directory)
    fd, temporary_name = tempfile.mkstemp(prefix=".camera-backup-", suffix=".tmp", dir=str(directory))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        path.chmod(0o600)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def read_backup(directory: Path, name: str) -> dict[str, object]:
    path = backup_path(directory, name)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("Sauvegarde caméra introuvable.")
    if path.stat().st_size > CAMERA_BACKUP_MAX_BYTES:
        raise CameraBackupError("Fichier de sauvegarde caméra trop volumineux.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CameraBackupError("Fichier de sauvegarde caméra illisible.") from exc
    return validate_backup(payload)


def preview_restore(current: dict[str, dict[str, object]], incoming: dict[str, dict[str, object]]) -> dict[str, object]:
    current_ids, incoming_ids = set(current), set(incoming)
    added = sorted(incoming_ids - current_ids)
    removed = sorted(current_ids - incoming_ids)
    modified: list[dict[str, object]] = []
    for camera_id in sorted(current_ids & incoming_ids):
        before, after = current[camera_id], incoming[camera_id]
        changed = [
            FIELD_LABELS.get(key, key)
            for key in FIELD_LABELS
            if before.get(key, False if key == "ptz_upside_down" else None) != after.get(key, False if key == "ptz_upside_down" else None)
        ]
        if changed:
            modified.append({"camera": camera_id, "fields": changed})
    return {
        "camera_count": len(incoming),
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": len(current_ids & incoming_ids) - len(modified),
        "secrets_included": True,
        "secrets_displayed": False,
    }
