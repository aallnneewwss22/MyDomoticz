#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Lance ce script avec sudo : sudo ./install.sh" >&2
  exit 1
fi

cat <<'WARNING'

============================================================
AVERTISSEMENT AVANT INSTALLATION / MISE A JOUR
============================================================

Cet installateur déploie ou met à jour les services de contrôle
et leurs unités systemd pour les environnements production et test.

PREREQUIS OBLIGATOIRES :
  Production : binaire /usr/local/bin/go2rtc
               YAML    /etc/go2rtc/go2rtc.yaml (ou chemin GO2RTC_CONFIG)
  Test       : binaire /home/pi/go2rtc-test/go2rtc
               YAML    /home/pi/go2rtc-test/go2rtc.yaml

Les deux binaires go2rtc et les deux fichiers YAML doivent déjà
exister et être correctement préparés. Cet installateur ne
télécharge, n'installe, ne met à jour et ne remplace AUCUN de
ces binaires ou fichiers YAML.

L'installateur installe/met à jour les services de contrôle,
leurs dépendances et leurs unités systemd. Il redémarre ensuite
les deux instances go2rtc et les deux services de contrôle :
les flux vidéo peuvent donc être momentanément interrompus.

Les fichiers d'environnement, jetons et registres caméra existants
sont préservés ; les registres ne sont ni copiés ni réinitialisés.

Vérifie les prérequis et dispose d'une sauvegarde vérifiée avant
de poursuivre. Consulter service/go2rtc-control/README.md et
MIGRATION.md pour la procédure complète.

WARNING

if [[ "${GO2RTC_INSTALL_CONFIRM:-}" != "oui" ]]; then
  if [[ ! -t 0 ]]; then
    echo "Installation annulée : confirme explicitement avec GO2RTC_INSTALL_CONFIRM=oui en mode non interactif." >&2
    exit 1
  fi
  read -r -p "Pour continuer, tape exactement OUI : " install_confirmation
  if [[ "${install_confirmation}" != "OUI" ]]; then
    echo "Installation annulée ; aucune modification n'a été effectuée." >&2
    exit 1
  fi
fi
echo "Confirmation reçue. Vérification des prérequis..."


SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SERVICE_USER:-pi}"
CONFIG_PATH="${GO2RTC_CONFIG:-/etc/go2rtc/go2rtc.yaml}"
GO2RTC_BIN="/usr/local/bin/go2rtc"
GO2RTC_INSTALL_DIR="/etc/go2rtc"
DASHBOARD_ORIGIN="${DASHBOARD_ORIGIN:-http://192.168.1.21:8080}"
INSTALL_DIR="/opt/go2rtc-control"
ETC_DIR="/etc/go2rtc-control"
GO2RTC_ENV="${GO2RTC_INSTALL_DIR}/go2rtc.env"

TEST_SERVICE_DIR="/home/pi/go2rtc-test"
TEST_BIN="${TEST_SERVICE_DIR}/go2rtc"
TEST_CONFIG="${TEST_SERVICE_DIR}/go2rtc.yaml"
TEST_INSTALL_DIR="/opt/go2rtc-control-test"
TEST_ETC_DIR="/etc/go2rtc-control-test"
TEST_ENV="${TEST_ETC_DIR}/go2rtc-control-test.env"

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "Utilisateur système introuvable : ${SERVICE_USER}" >&2
  exit 1
fi
if [[ ! -x "${GO2RTC_BIN}" ]]; then
  echo "Binaire go2rtc introuvable ou non exécutable : ${GO2RTC_BIN}" >&2
  echo "Installe une copie indépendante du binaire de production avant de poursuivre." >&2
  exit 1
fi
if [[ ! -r "${CONFIG_PATH}" ]]; then
  echo "Configuration go2rtc de production introuvable ou illisible : ${CONFIG_PATH}" >&2
  echo "Copie d'abord la configuration de production selon MIGRATION.md." >&2
  exit 1
fi
if [[ ! -x "${TEST_BIN}" ]]; then
  echo "Binaire go2rtc de test introuvable ou non exécutable : ${TEST_BIN}" >&2
  echo "Prépare d'abord l'instance de test indépendante selon MIGRATION.md." >&2
  exit 1
fi
if [[ ! -r "${TEST_CONFIG}" ]]; then
  echo "Configuration go2rtc de test introuvable ou illisible : ${TEST_CONFIG}" >&2
  echo "Prépare d'abord le YAML de test indépendant selon MIGRATION.md." >&2
  exit 1
fi
if [[ -f "${GO2RTC_ENV}" ]]; then
  config_line_count="$(grep -cE '^[[:space:]]*GO2RTC_CONFIG[[:space:]]*=' "${GO2RTC_ENV}" || true)"
  configured_path="$(sed -n 's/^[[:space:]]*GO2RTC_CONFIG[[:space:]]*=[[:space:]]*//p' "${GO2RTC_ENV}" | tail -n 1 | sed -E 's/[[:space:]]+$//')"
  configured_path="${configured_path%\"}"
  configured_path="${configured_path#\"}"
  configured_path="${configured_path%\'}"
  configured_path="${configured_path#\'}"
  if [[ "${config_line_count}" -ne 1 || "${configured_path}" != "${CONFIG_PATH}" ]]; then
    echo "Configuration de production incohérente : GO2RTC_CONFIG dans ${GO2RTC_ENV} doit désigner ${CONFIG_PATH} exactement une fois." >&2
    echo "Corrige ce fichier manuellement après sauvegarde ; l'installateur n'écrase pas les paramètres existants." >&2
    exit 1
  fi
fi

apt-get update
apt-get install -y python3-yaml python3-zeep python3-pip

read_env_value() {
  local file="$1" key="$2" value
  [[ -f "$file" ]] || return 0
  value="$(sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1)"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

ensure_env_value() {
  local file="$1" key="$2" value="$3"
  if ! grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$file"; then
    printf '%s=%s\n' "$key" "$value" >> "$file"
  fi
}

validate_env_value() {
  local file="$1" key="$2" expected="$3" actual
  actual="$(read_env_value "$file" "$key")"
  if [[ "$actual" != "$expected" ]]; then
    echo "Configuration incohérente : ${key} dans ${file} doit désigner ${expected}." >&2
    echo "Corrige ce fichier manuellement après sauvegarde ; l'installateur ne remplace pas les paramètres existants." >&2
    exit 1
  fi
}

install -d -o root -g "${SERVICE_USER}" -m 0750 "${INSTALL_DIR}" "${ETC_DIR}" "${GO2RTC_INSTALL_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0700 /var/lib/go2rtc-control/settings-backups /var/lib/go2rtc-control/profile-library /var/lib/go2rtc-control-test/settings-backups /var/lib/go2rtc-control-test/profile-library
install -d -o root -g "${SERVICE_USER}" -m 0750 "${TEST_INSTALL_DIR}" "${TEST_ETC_DIR}"
if [[ ! -f "${GO2RTC_ENV}" ]]; then
  printf 'GO2RTC_CONFIG=%s\n' "${CONFIG_PATH}" > "${GO2RTC_ENV}"
  chown root:"${SERVICE_USER}" "${GO2RTC_ENV}"
  chmod 0640 "${GO2RTC_ENV}"
fi
for target_dir in "${INSTALL_DIR}" "${TEST_INSTALL_DIR}"; do
  install -o root -g root -m 0644 "${SCRIPT_DIR}/server.py" "${target_dir}/server.py"
  install -o root -g root -m 0644 "${SCRIPT_DIR}/media_gateway.py" "${target_dir}/media_gateway.py"
  install -o root -g root -m 0644 "${SCRIPT_DIR}/camera_profiles.py" "${target_dir}/camera_profiles.py"
  install -o root -g root -m 0644 "${SCRIPT_DIR}/profile_library.py" "${target_dir}/profile_library.py"
  install -o root -g root -m 0644 "${SCRIPT_DIR}/recovery_auth.py" "${target_dir}/recovery_auth.py"
  install -o root -g root -m 0644 "${SCRIPT_DIR}/session_manager.py" "${target_dir}/session_manager.py"
  install -o root -g root -m 0644 "${SCRIPT_DIR}/transcode_engine.py" "${target_dir}/transcode_engine.py"
done
install -d -o root -g root -m 0755 "${INSTALL_DIR}/vendor"
pip3 install --disable-pip-version-check --no-deps --target "${INSTALL_DIR}/vendor" "onvif-zeep==0.2.12"

# onvif-zeep 0.2.12 ships its WSDL resources in the source archive, but its
# wheel/--target installation does not place them beside the onvif module.
# Retrieve the matching sdist and copy the complete WSDL tree into vendor.
WSDL_TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${WSDL_TMP_DIR}"' EXIT
pip3 download --disable-pip-version-check --no-deps --no-binary=:all: \
  --dest "${WSDL_TMP_DIR}" "onvif-zeep==0.2.12"
WSDL_ARCHIVE="${WSDL_TMP_DIR}/onvif_zeep-0.2.12.tar.gz"
echo "aa8bbc02a73eaa50894b0c18e39fa8d318a583a664c65bf35b3c8029d1c40b49  ${WSDL_ARCHIVE}" | sha256sum --check -
tar -xzf "${WSDL_ARCHIVE}" -C "${WSDL_TMP_DIR}"
WSDL_SOURCE_DIR="${WSDL_TMP_DIR}/onvif_zeep-0.2.12/wsdl"
if [[ ! -s "${WSDL_SOURCE_DIR}/devicemgmt.wsdl" || ! -s "${WSDL_SOURCE_DIR}/media.wsdl" || ! -s "${WSDL_SOURCE_DIR}/ptz.wsdl" ]]; then
  echo "Les fichiers WSDL requis sont absents de l'archive onvif-zeep 0.2.12." >&2
  exit 1
fi
rm -rf "${INSTALL_DIR}/vendor/wsdl"
install -d -o root -g root -m 0755 "${INSTALL_DIR}/vendor/wsdl"
cp -a "${WSDL_SOURCE_DIR}/." "${INSTALL_DIR}/vendor/wsdl/"
chown -R root:root "${INSTALL_DIR}/vendor/wsdl"
chmod -R a+rX "${INSTALL_DIR}/vendor/wsdl"
install -d -o root -g root -m 0755 "${TEST_INSTALL_DIR}/vendor"
cp -a "${INSTALL_DIR}/vendor/." "${TEST_INSTALL_DIR}/vendor/"
chown -R root:root "${TEST_INSTALL_DIR}/vendor"
chmod -R a+rX "${TEST_INSTALL_DIR}/vendor"
install -o root -g root -m 0644 "${SCRIPT_DIR}/go2rtc.service" /etc/systemd/system/go2rtc.service
install -o root -g root -m 0644 "${SCRIPT_DIR}/go2rtc-control.service" /etc/systemd/system/go2rtc-control.service
install -o root -g root -m 0644 "${SCRIPT_DIR}/go2rtc-test.service.example" /etc/systemd/system/go2rtc-test.service
install -o root -g root -m 0644 "${SCRIPT_DIR}/go2rtc-control-test.service" /etc/systemd/system/go2rtc-control-test.service

install -o root -g root -m 0755 "${SCRIPT_DIR}/show-token.sh" /usr/local/sbin/go2rtc-control-show-token
install -o root -g root -m 0755 "${SCRIPT_DIR}/recovery-key-admin.py" /usr/local/sbin/go2rtc-control-recovery-key

if [[ ! -f "${ETC_DIR}/go2rtc-control.env" ]]; then
  cat > "${ETC_DIR}/go2rtc-control.env" <<EOF
GO2RTC_API=http://127.0.0.1:1984
GO2RTC_CONFIG=${CONFIG_PATH}
SOURCE_REGISTRY=/var/lib/go2rtc-control/cameras.json
SETTINGS_BACKUP_DIR=/var/lib/go2rtc-control/settings-backups
PROFILE_LIBRARY_DIR=/var/lib/go2rtc-control/profile-library
RECOVERY_KEY_FILE=/var/lib/go2rtc-control/recovery/recovery-key.json
TOKEN_FILE=${ETC_DIR}/token
DASHBOARD_ORIGIN=${DASHBOARD_ORIGIN}
CONTROL_HOST=0.0.0.0
CONTROL_PORT=1985
TRANSCODE_FFMPEG=/usr/bin/ffmpeg
TRANSCODE_RTSP_HOST=127.0.0.1
TRANSCODE_RTSP_PORT=8554
EOF
  chown root:"${SERVICE_USER}" "${ETC_DIR}/go2rtc-control.env"
  chmod 0640 "${ETC_DIR}/go2rtc-control.env"
else
  # Add missing defaults without replacing existing user-defined settings.
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" GO2RTC_API http://127.0.0.1:1984
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" GO2RTC_CONFIG "${CONFIG_PATH}"
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" SOURCE_REGISTRY /var/lib/go2rtc-control/cameras.json
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" SETTINGS_BACKUP_DIR /var/lib/go2rtc-control/settings-backups
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" PROFILE_LIBRARY_DIR /var/lib/go2rtc-control/profile-library
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" RECOVERY_KEY_FILE /var/lib/go2rtc-control/recovery/recovery-key.json
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" TOKEN_FILE "${ETC_DIR}/token"
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" CONTROL_HOST 0.0.0.0
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" CONTROL_PORT 1985
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" TRANSCODE_FFMPEG /usr/bin/ffmpeg
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" TRANSCODE_RTSP_HOST 127.0.0.1
  ensure_env_value "${ETC_DIR}/go2rtc-control.env" TRANSCODE_RTSP_PORT 8554
fi
validate_env_value "${ETC_DIR}/go2rtc-control.env" GO2RTC_API http://127.0.0.1:1984
validate_env_value "${ETC_DIR}/go2rtc-control.env" GO2RTC_CONFIG "${CONFIG_PATH}"
validate_env_value "${ETC_DIR}/go2rtc-control.env" CONTROL_HOST 0.0.0.0
validate_env_value "${ETC_DIR}/go2rtc-control.env" CONTROL_PORT 1985
validate_env_value "${ETC_DIR}/go2rtc-control.env" SOURCE_REGISTRY /var/lib/go2rtc-control/cameras.json
validate_env_value "${ETC_DIR}/go2rtc-control.env" SETTINGS_BACKUP_DIR /var/lib/go2rtc-control/settings-backups
validate_env_value "${ETC_DIR}/go2rtc-control.env" PROFILE_LIBRARY_DIR /var/lib/go2rtc-control/profile-library
validate_env_value "${ETC_DIR}/go2rtc-control.env" RECOVERY_KEY_FILE /var/lib/go2rtc-control/recovery/recovery-key.json
validate_env_value "${ETC_DIR}/go2rtc-control.env" TRANSCODE_RTSP_PORT 8554

ensure_env_value "${ETC_DIR}/go2rtc-control.env" TOKEN_FILE "${ETC_DIR}/token"
PROD_TOKEN_FILE="$(read_env_value "${ETC_DIR}/go2rtc-control.env" TOKEN_FILE)"
if [[ -z "${PROD_TOKEN_FILE}" ]]; then
  echo "TOKEN_FILE est absent de ${ETC_DIR}/go2rtc-control.env." >&2
  exit 1
fi
if [[ ! -e "${PROD_TOKEN_FILE}" ]]; then
  install -d -o root -g "${SERVICE_USER}" -m 0750 "$(dirname -- "${PROD_TOKEN_FILE}")"
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "${PROD_TOKEN_FILE}"
elif [[ ! -f "${PROD_TOKEN_FILE}" || -L "${PROD_TOKEN_FILE}" || ! -s "${PROD_TOKEN_FILE}" ]]; then
  echo "Fichier de jeton de production invalide ; aucun remplacement automatique n'est effectué." >&2
  exit 1
fi
chown root:"${SERVICE_USER}" "${PROD_TOKEN_FILE}"
chmod 0640 "${PROD_TOKEN_FILE}"

# Configure the isolated test control API without replacing an existing env file,
# token, or camera registry.
if [[ ! -f "${TEST_ENV}" ]]; then
  cat > "${TEST_ENV}" <<EOF
GO2RTC_API=http://127.0.0.1:1987
GO2RTC_CONFIG=${TEST_CONFIG}
SOURCE_REGISTRY=/var/lib/go2rtc-control-test/cameras.json
SETTINGS_BACKUP_DIR=/var/lib/go2rtc-control-test/settings-backups
PROFILE_LIBRARY_DIR=/var/lib/go2rtc-control-test/profile-library
RECOVERY_KEY_FILE=/var/lib/go2rtc-control-test/recovery/recovery-key.json
TOKEN_FILE=${TEST_ETC_DIR}/token
CONTROL_HOST=127.0.0.1
CONTROL_PORT=1986
TRANSCODE_FFMPEG=/usr/bin/ffmpeg
TRANSCODE_RTSP_HOST=127.0.0.1
TRANSCODE_RTSP_PORT=8556
EOF
  chown root:"${SERVICE_USER}" "${TEST_ENV}"
  chmod 0640 "${TEST_ENV}"
else
  ensure_env_value "${TEST_ENV}" GO2RTC_API http://127.0.0.1:1987
  ensure_env_value "${TEST_ENV}" GO2RTC_CONFIG "${TEST_CONFIG}"
  ensure_env_value "${TEST_ENV}" SOURCE_REGISTRY /var/lib/go2rtc-control-test/cameras.json
  ensure_env_value "${TEST_ENV}" SETTINGS_BACKUP_DIR /var/lib/go2rtc-control-test/settings-backups
  ensure_env_value "${TEST_ENV}" PROFILE_LIBRARY_DIR /var/lib/go2rtc-control-test/profile-library
  ensure_env_value "${TEST_ENV}" RECOVERY_KEY_FILE /var/lib/go2rtc-control-test/recovery/recovery-key.json
  ensure_env_value "${TEST_ENV}" TOKEN_FILE "${TEST_ETC_DIR}/token"
  ensure_env_value "${TEST_ENV}" CONTROL_HOST 127.0.0.1
  ensure_env_value "${TEST_ENV}" CONTROL_PORT 1986
  ensure_env_value "${TEST_ENV}" TRANSCODE_FFMPEG /usr/bin/ffmpeg
  ensure_env_value "${TEST_ENV}" TRANSCODE_RTSP_HOST 127.0.0.1
  ensure_env_value "${TEST_ENV}" TRANSCODE_RTSP_PORT 8556
fi
validate_env_value "${TEST_ENV}" GO2RTC_API http://127.0.0.1:1987
validate_env_value "${TEST_ENV}" GO2RTC_CONFIG "${TEST_CONFIG}"
validate_env_value "${TEST_ENV}" CONTROL_HOST 127.0.0.1
validate_env_value "${TEST_ENV}" CONTROL_PORT 1986
validate_env_value "${TEST_ENV}" SOURCE_REGISTRY /var/lib/go2rtc-control-test/cameras.json
validate_env_value "${TEST_ENV}" SETTINGS_BACKUP_DIR /var/lib/go2rtc-control-test/settings-backups
validate_env_value "${TEST_ENV}" PROFILE_LIBRARY_DIR /var/lib/go2rtc-control-test/profile-library
validate_env_value "${TEST_ENV}" RECOVERY_KEY_FILE /var/lib/go2rtc-control-test/recovery/recovery-key.json
validate_env_value "${TEST_ENV}" TRANSCODE_RTSP_PORT 8556

TEST_TOKEN_FILE="$(read_env_value "${TEST_ENV}" TOKEN_FILE)"
if [[ -z "${TEST_TOKEN_FILE}" ]]; then
  echo "TOKEN_FILE est absent de ${TEST_ENV}." >&2
  exit 1
fi
if [[ ! -e "${TEST_TOKEN_FILE}" ]]; then
  install -d -o root -g "${SERVICE_USER}" -m 0750 "$(dirname -- "${TEST_TOKEN_FILE}")"
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "${TEST_TOKEN_FILE}"
elif [[ ! -f "${TEST_TOKEN_FILE}" || -L "${TEST_TOKEN_FILE}" || ! -s "${TEST_TOKEN_FILE}" ]]; then
  echo "Fichier de jeton de test invalide ; aucun remplacement automatique n'est effectué." >&2
  exit 1
fi
chown root:"${SERVICE_USER}" "${TEST_TOKEN_FILE}"
chmod 0640 "${TEST_TOKEN_FILE}"

# Do not create, replace, copy, or merge either SOURCE_REGISTRY. The services
# retain ownership of their own existing persistent camera state.
systemctl daemon-reload
systemctl enable go2rtc.service go2rtc-control.service go2rtc-test.service go2rtc-control-test.service
systemctl restart go2rtc.service
systemctl restart go2rtc-test.service
systemctl restart go2rtc-control.service
systemctl restart go2rtc-control-test.service

echo
echo "Les deux environnements go2rtc et leurs API de contrôle sont installés/mis à jour et démarrés."
echo "Production : API go2rtc 1984, contrôle 1985, registre /var/lib/go2rtc-control/cameras.json."
echo "Test : API go2rtc 1987, contrôle 127.0.0.1:1986, registre /var/lib/go2rtc-control-test/cameras.json."
echo "Les registres et jetons existants ne sont ni remplacés ni fusionnés."
echo "Configuration production : ${ETC_DIR}/go2rtc-control.env"
echo "Configuration test : ${TEST_ENV}"
echo "Jeton production : sudo go2rtc-control-show-token"
echo "Jeton test : sudo go2rtc-control-show-token --test"
echo "Aucun jeton n’est affiché automatiquement pendant l’installation ou une mise à jour."
echo
echo "Vérifie que le port TCP 1985 reste limité à ton réseau local."
