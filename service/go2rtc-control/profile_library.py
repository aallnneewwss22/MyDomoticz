"""Shared, Raspberry Pi-local library for reusable camera profiles."""
from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from camera_profiles import CameraProfileError, normalize_camera_profiles

PROFILE_LIBRARY_FORMAT = "mydomoticz-camera-profile-library"
PROFILE_LIBRARY_VERSION = 1
PROFILE_LIBRARY_MAX_BYTES = 64 * 1024
PROFILE_LIBRARY_FILENAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\\.json$")
_VALIDATION_ID = "00000000000000000000000000000000"
_PROFILE_FIELDS = {"name", "width", "height", "fps", "bitrate_kbps"}


class ProfileLibraryError(ValueError):
    """A library entry is invalid or cannot be addressed safely."""


def profile_library_filename(profile_name: object) -> str:
    if not isinstance(profile_name, str) or not profile_name.strip() or len(profile_name.strip()) > 64:
        raise ProfileLibraryError("Nom de profil invalide.")
    ascii_name = unicodedata.normalize("NFKD", profile_name.strip()).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-").lower()[:64].strip("-")
    if not slug:
        raise ProfileLibraryError("Le nom du profil ne permet pas de créer un nom de fichier sûr.")
    return slug + ".json"


def _validate_profile(profile: object) -> dict[str, Any]:
    if not isinstance(profile, dict) or set(profile) != _PROFILE_FIELDS:
        raise ProfileLibraryError("Les champs du profil sont absents ou invalides.")
    candidate = dict(profile, type="transcode")
    try:
        normalized, _ = normalize_camera_profiles(
            {_VALIDATION_ID: candidate}, "native", "1080p", enforce_native_limit=False
        )
    except CameraProfileError as exc:
        raise ProfileLibraryError(str(exc)) from exc
    item = normalized[_VALIDATION_ID]
    return {
        "name": item["name"],
        "width": item["width"],
        "height": item["height"],
        "fps": item["fps"],
        "bitrate_kbps": item["bitrate_kbps"],
    }


def ensure_profile_library_dir(directory: Path) -> None:
    if directory.is_symlink():
        raise OSError("Le répertoire de la bibliothèque ne peut pas être un lien symbolique.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)


def _entry_path(directory: Path, filename: object) -> Path:
    if not isinstance(filename, str) or not PROFILE_LIBRARY_FILENAME.fullmatch(filename):
        raise ProfileLibraryError("Nom de fichier de profil invalide.")
    return directory / filename


def _read_entry(path: Path, filename: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("Profil de bibliothèque introuvable.")
    if path.stat().st_size > PROFILE_LIBRARY_MAX_BYTES:
        raise ProfileLibraryError("Fichier de profil trop volumineux.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileLibraryError("Fichier de profil illisible ou invalide.") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"format", "version", "profile"}
        or payload.get("format") != PROFILE_LIBRARY_FORMAT
        or payload.get("version") != PROFILE_LIBRARY_VERSION
    ):
        raise ProfileLibraryError("Format de profil non reconnu.")
    profile = _validate_profile(payload.get("profile"))
    if profile_library_filename(profile["name"]) != filename:
        raise ProfileLibraryError("Le nom du fichier ne correspond pas au nom du profil.")
    return profile


def list_profile_library(directory: Path) -> list[dict[str, Any]]:
    ensure_profile_library_dir(directory)
    result = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if not PROFILE_LIBRARY_FILENAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
            continue
        try:
            profile = _read_entry(path, path.name)
            result.append({
                "filename": path.name,
                "name": profile["name"],
                "width": profile["width"],
                "height": profile["height"],
                "fps": profile["fps"],
                "bitrate_kbps": profile["bitrate_kbps"],
                "valid": True,
            })
        except (ProfileLibraryError, FileNotFoundError):
            # Keep invalid entries visible so that an administrator can remove them.
            result.append({"filename": path.name, "name": path.stem, "valid": False})
    return result


def read_profile_library_entry(directory: Path, filename: str) -> dict[str, Any]:
    ensure_profile_library_dir(directory)
    path = _entry_path(directory, filename)
    return {"filename": filename, "profile": _read_entry(path, filename)}


def save_profile_library_entry(
    directory: Path,
    profile: object,
    *,
    overwrite: bool = False,
    expected_filename: str | None = None,
) -> dict[str, Any]:
    normalized = _validate_profile(profile)
    filename = profile_library_filename(normalized["name"])
    if expected_filename is not None and expected_filename != filename:
        raise ProfileLibraryError("Le nom du fichier ne correspond pas au nom du profil.")
    ensure_profile_library_dir(directory)
    path = _entry_path(directory, filename)
    if path.is_symlink():
        raise ProfileLibraryError("Un fichier symbolique ne peut pas être remplacé.")
    if path.exists():
        if not overwrite:
            raise FileExistsError(filename)
        try:
            existing = _read_entry(path, filename)
        except ProfileLibraryError:
            existing = None
        if existing is not None and existing["name"].casefold() != normalized["name"].casefold():
            raise ProfileLibraryError("Un autre profil utilise déjà ce nom de fichier. Renomme le profil avant de l'enregistrer.")
    payload = {
        "format": PROFILE_LIBRARY_FORMAT,
        "version": PROFILE_LIBRARY_VERSION,
        "profile": normalized,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\\n").encode("utf-8")
    if len(encoded) > PROFILE_LIBRARY_MAX_BYTES:
        raise ProfileLibraryError("Fichier de profil trop volumineux.")
    fd, temporary_name = tempfile.mkstemp(prefix=".profile-", suffix=".tmp", dir=str(directory))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {"filename": filename, "profile": normalized}


def delete_profile_library_entry(directory: Path, filename: str) -> None:
    ensure_profile_library_dir(directory)
    path = _entry_path(directory, filename)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("Profil de bibliothèque introuvable.")
    path.unlink()
