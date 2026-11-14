#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Lance ce script avec sudo : sudo ./install.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SERVICE_USER:-pi}"
CONFIG_PATH="${GO2RTC_CONFIG:-/etc/go2rtc/go2rtc.yaml}"
GO2RTC_BIN="${GO2RTC_BIN:-/usr/local/bin/go2rtc}"
GO2RTC_INSTALL_DIR="/etc/go2rtc"
DASHBOARD_ORIGIN="${DASHBOARD_ORIGIN:-http://192.168.1.21:8080}"
INSTALL_DIR="/opt/go2rtc-control"
ETC_DIR="/etc/go2rtc-control"

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
  echo "Copie d'abord la configuration actuelle vers /etc/go2rtc/go2rtc.yaml selon MIGRATION.md." >&2
  exit 1
fi

apt-get update
apt-get install -y python3-yaml python3-zeep python3-pip

install -d -o root -g "${SERVICE_USER}" -m 0750 "${INSTALL_DIR}" "${ETC_DIR}" "${GO2RTC_INSTALL_DIR}"
install -o root -g root -m 0644 "${SCRIPT_DIR}/server.py" "${INSTALL_DIR}/server.py"
install -o root -g root -m 0644 "${SCRIPT_DIR}/camera_profiles.py" "${INSTALL_DIR}/camera_profiles.py"
install -o root -g root -m 0644 "${SCRIPT_DIR}/session_manager.py" "${INSTALL_DIR}/session_manager.py"
install -o root -g root -m 0644 "${SCRIPT_DIR}/transcode_engine.py" "${INSTALL_DIR}/transcode_engine.py"
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
install -o root -g root -m 0644 "${SCRIPT_DIR}/go2rtc.service" /etc/systemd/system/go2rtc.service
install -o root -g root -m 0644 "${SCRIPT_DIR}/go2rtc-control.service" /etc/systemd/system/go2rtc-control.service

if [[ ! -s "${ETC_DIR}/token" ]]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "${ETC_DIR}/token"
fi
chown root:"${SERVICE_USER}" "${ETC_DIR}/token"
chmod 0640 "${ETC_DIR}/token"

if [[ ! -f "${ETC_DIR}/go2rtc-control.env" ]]; then
  cat > "${ETC_DIR}/go2rtc-control.env" <<EOF
GO2RTC_API=http://127.0.0.1:1984
GO2RTC_CONFIG=${CONFIG_PATH}
SOURCE_REGISTRY=/var/lib/go2rtc-control/cameras.json
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
  # Add engine defaults without replacing existing user-defined settings.
  grep -q '^SOURCE_REGISTRY=' "${ETC_DIR}/go2rtc-control.env" || printf '\nSOURCE_REGISTRY=/var/lib/go2rtc-control/cameras.json\n' >> "${ETC_DIR}/go2rtc-control.env"
  grep -q '^TRANSCODE_FFMPEG=' "${ETC_DIR}/go2rtc-control.env" || printf 'TRANSCODE_FFMPEG=/usr/bin/ffmpeg\n' >> "${ETC_DIR}/go2rtc-control.env"
  grep -q '^TRANSCODE_RTSP_HOST=' "${ETC_DIR}/go2rtc-control.env" || printf 'TRANSCODE_RTSP_HOST=127.0.0.1\n' >> "${ETC_DIR}/go2rtc-control.env"
  grep -q '^TRANSCODE_RTSP_PORT=' "${ETC_DIR}/go2rtc-control.env" || printf 'TRANSCODE_RTSP_PORT=8554\n' >> "${ETC_DIR}/go2rtc-control.env"
fi

systemctl daemon-reload
systemctl enable go2rtc.service go2rtc-control.service
systemctl restart go2rtc.service
systemctl restart go2rtc-control.service

echo
echo "Service installé/mis à jour et démarré."
echo "Les sources caméra sont copiées une seule fois dans /var/lib/go2rtc-control/cameras.json."
echo "Le registre est indépendant du YAML go2rtc et n'est jamais réinitialisé lors d'une mise à jour."
echo "Configuration : ${ETC_DIR}/go2rtc-control.env"
echo "Jeton à saisir dans les paramètres du tableau de bord (inchangé lors d'une mise à jour) :"
cat "${ETC_DIR}/token"
echo
echo "Vérifie que le port TCP 1985 reste limité à ton réseau local."
