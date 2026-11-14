"""Persistent per-camera video profile model.

This module deliberately has no HTTP, go2rtc, or FFmpeg side effects. It
normalizes the profile data stored alongside each camera in cameras.json.
"""
from __future__ import annotations

import re
import secrets
from typing import Any

NATIVE_PROFILE_ID = "native"
NATIVE_PROFILE = {
    "id": NATIVE_PROFILE_ID,
    "name": "Natif",
    "type": "native",
}
NATIVE_DIMENSIONS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}
ALLOWED_RESOLUTIONS = {
    (1920, 1080),
    (1280, 720),
    (854, 480),
    (640, 360),
}
ALLOWED_FPS = {15, 10, 5, 2, 1, 0.5, 0.2}
MIN_BITRATE_KBPS = 50
MAX_BITRATE_KBPS = 2000
PROFILE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_PROFILE_NAME_LENGTH = 64


class CameraProfileError(ValueError):
    """A persisted camera profile is invalid."""


def normalize_camera_profiles(
    profiles: object,
    default_profile_id: object,
    native_quality: object,
    *,
    enforce_native_limit: bool = True,
) -> tuple[dict[str, dict[str, Any]], str]:
    """Return canonical profiles and the mandatory native default.

    The native source resolution is stored separately in the camera settings.
    Transcode profiles describe only the output dimensions, frame rate and
    target bitrate; the API will combine them with the current native source
    when it later requests a transcode session.
    """
    if not isinstance(native_quality, str) or native_quality not in NATIVE_DIMENSIONS:
        raise CameraProfileError("La résolution native de la caméra est invalide.")
    if profiles is None:
        profiles = {}
    if not isinstance(profiles, dict):
        raise CameraProfileError("La liste des profils de la caméra doit être un objet JSON.")

    native = profiles.get(NATIVE_PROFILE_ID)
    if NATIVE_PROFILE_ID in profiles and native != NATIVE_PROFILE:
        raise CameraProfileError("Le profil Natif est réservé et ne peut pas être modifié.")

    native_width, native_height = NATIVE_DIMENSIONS[str(native_quality)]
    normalized: dict[str, dict[str, Any]] = {
        NATIVE_PROFILE_ID: dict(NATIVE_PROFILE)
    }
    used_names = {NATIVE_PROFILE["name"].casefold()}

    for profile_id, profile in profiles.items():
        if profile_id == NATIVE_PROFILE_ID:
            continue
        if not isinstance(profile_id, str) or not PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise CameraProfileError("Identifiant interne de profil invalide.")
        if not isinstance(profile, dict):
            raise CameraProfileError("Un profil vidéo doit être un objet JSON.")
        if profile.get("type") != "transcode":
            raise CameraProfileError("Les profils personnalisés doivent être de type transcode.")

        name = profile.get("name")
        if not isinstance(name, str):
            raise CameraProfileError("Le nom du profil doit être du texte.")
        name = name.strip()
        if not name or len(name) > MAX_PROFILE_NAME_LENGTH:
            raise CameraProfileError(
                f"Le nom du profil doit contenir entre 1 et {MAX_PROFILE_NAME_LENGTH} caractères."
            )
        normalized_name = name.casefold()
        if normalized_name in used_names:
            raise CameraProfileError("Chaque profil doit avoir un nom unique pour cette caméra.")
        used_names.add(normalized_name)

        width, height = profile.get("width"), profile.get("height")
        if (
            isinstance(width, bool) or not isinstance(width, int)
            or isinstance(height, bool) or not isinstance(height, int)
            or (width, height) not in ALLOWED_RESOLUTIONS
        ):
            raise CameraProfileError("Résolution de sortie non autorisée.")
        if enforce_native_limit and (width > native_width or height > native_height):
            raise CameraProfileError("Un profil ne peut pas dépasser la résolution native de la caméra.")

        fps = profile.get("fps")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps not in ALLOWED_FPS:
            raise CameraProfileError("Cadence IPS non autorisée.")

        bitrate = profile.get("bitrate_kbps")
        if (
            isinstance(bitrate, bool) or not isinstance(bitrate, int)
            or not MIN_BITRATE_KBPS <= bitrate <= MAX_BITRATE_KBPS
        ):
            raise CameraProfileError(
                f"Le débit cible doit être compris entre {MIN_BITRATE_KBPS} et {MAX_BITRATE_KBPS} kbit/s."
            )

        normalized[profile_id] = {
            "id": profile_id,
            "name": name,
            "type": "transcode",
            "width": width,
            "height": height,
            "fps": float(fps),
            "bitrate_kbps": bitrate,
        }

    if default_profile_id is None:
        default_profile_id = NATIVE_PROFILE_ID
    if default_profile_id != NATIVE_PROFILE_ID:
        raise CameraProfileError("Le profil par défaut doit rester Natif.")

    return normalized, NATIVE_PROFILE_ID


def validate_selected_profile(profiles: dict[str, dict[str, Any]], selected_profile_id: object) -> str:
    if selected_profile_id is None:
        return NATIVE_PROFILE_ID
    if not isinstance(selected_profile_id, str) or selected_profile_id not in profiles:
        raise CameraProfileError("Le profil sélectionné n'existe pas pour cette caméra.")
    return selected_profile_id


def create_camera_profile(profiles: dict[str, dict[str, Any]], native_quality: object, payload: object):
    if not isinstance(payload, dict) or set(payload) != {"name", "width", "height", "fps", "bitrate_kbps"}:
        raise CameraProfileError("Les champs requis du profil sont absents ou invalides.")
    profile_id = secrets.token_hex(16)
    candidate = dict(profiles)
    candidate[profile_id] = dict(payload, type="transcode")
    normalized, _ = normalize_camera_profiles(candidate, NATIVE_PROFILE_ID, native_quality)
    return normalized, profile_id


def update_camera_profile(profiles: dict[str, dict[str, Any]], native_quality: object, profile_id: object, payload: object):
    if not isinstance(profile_id, str) or profile_id == NATIVE_PROFILE_ID or profile_id not in profiles:
        raise CameraProfileError("Profil vidéo introuvable ou non modifiable.")
    if not isinstance(payload, dict) or not payload or set(payload) - {"name", "width", "height", "fps", "bitrate_kbps"}:
        raise CameraProfileError("Le profil contient un champ non modifiable ou aucune modification.")
    candidate = dict(profiles)
    updated = dict(candidate[profile_id])
    updated.update(payload)
    candidate[profile_id] = updated
    normalized, _ = normalize_camera_profiles(candidate, NATIVE_PROFILE_ID, native_quality)
    return normalized


def delete_camera_profile(profiles: dict[str, dict[str, Any]], profile_id: object):
    if not isinstance(profile_id, str) or profile_id == NATIVE_PROFILE_ID or profile_id not in profiles:
        raise CameraProfileError("Profil vidéo introuvable ou non supprimable.")
    candidate = dict(profiles)
    del candidate[profile_id]
    return candidate
