#!/usr/bin/env python3
"""Local administrator command to bootstrap or rotate the recovery key.

This command is intentionally local-only: it requires root and never exposes an
HTTP endpoint that could create a recovery credential without authentication.
"""
from __future__ import annotations

import argparse
import os
import pwd
import sys
from pathlib import Path

PRODUCTION_ENV = Path("/etc/go2rtc-control/go2rtc-control.env")
TEST_ENV = Path("/etc/go2rtc-control-test/go2rtc-control-test.env")
PRODUCTION_DEFAULT = Path("/var/lib/go2rtc-control/recovery/recovery-key.json")
TEST_DEFAULT = Path("/var/lib/go2rtc-control-test/recovery/recovery-key.json")
MODULE_DIR = Path("/opt/go2rtc-control")


def configured_key_path(env_file: Path, default: Path) -> Path:
    """Read only RECOVERY_KEY_FILE; never source or execute the environment file."""
    if not env_file.exists():
        return default
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "RECOVERY_KEY_FILE":
            value = value.strip().strip("\"").strip("'")
            if value:
                return Path(value)
    return default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialiser ou renouveler localement la clé de récupération MyDomoticz."
    )
    parser.add_argument("--test", action="store_true", help="utiliser l'environnement de test isolé")
    parser.add_argument("--rotate", action="store_true", help="remplacer une clé déjà existante")
    args = parser.parse_args(argv)

    if os.geteuid() != 0:
        parser.error("exécuter cette commande avec sudo")
    if not sys.stdout.isatty():
        parser.error("la clé ne peut être affichée que dans un terminal interactif")

    env_file = TEST_ENV if args.test else PRODUCTION_ENV
    default_path = TEST_DEFAULT if args.test else PRODUCTION_DEFAULT
    key_path = configured_key_path(env_file, default_path)
    if key_path.exists() or key_path.is_symlink():
        if not args.rotate:
            print(
                f"Une clé existe déjà ({key_path}). Aucune modification effectuée. "
                "Pour la remplacer volontairement, ajoute --rotate.",
                file=sys.stderr,
            )
            return 2
        confirmation = input("Le renouvellement invalidera l'ancienne clé. Tape ROTATE pour confirmer : ")
        if confirmation != "ROTATE":
            print("Renouvellement annulé ; aucune modification effectuée.")
            return 1

    service_user = os.environ.get("GO2RTC_CONTROL_SERVICE_USER", "pi")
    try:
        account = pwd.getpwnam(service_user)
    except KeyError:
        print(f"Compte du service introuvable : {service_user}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(MODULE_DIR))
    try:
        from recovery_auth import RecoveryAuth
    except ImportError as exc:
        print(f"Module de récupération introuvable dans {MODULE_DIR}: {exc}", file=sys.stderr)
        return 2

    try:
        key = RecoveryAuth(key_path).create_or_rotate_key()
        os.chown(key_path.parent, account.pw_uid, account.pw_gid)
        os.chmod(key_path.parent, 0o700)
        os.chown(key_path, account.pw_uid, account.pw_gid)
        os.chmod(key_path, 0o600)
    except Exception as exc:
        print(f"Impossible de créer la clé de récupération : {exc}", file=sys.stderr)
        return 2

    environment = "test" if args.test else "production"
    print(f"Clé de récupération ({environment}) — à conserver immédiatement dans un endroit sûr :")
    print(key)
    print("Cette clé ne sera plus affichée. Ne la place pas dans un fichier du Raspberry Pi ni dans un journal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
