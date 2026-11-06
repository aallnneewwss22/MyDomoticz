#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Lance ce script avec sudo : sudo ./install.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${SERVICE_USER:-pi}"
CONFIG_PATH="${GO2RTC_CONFIG:-/home/pi/go2rtc-test/go2rtc.yaml}"
DASHBOARD_ORIGIN="${DASHBOARD_ORIGIN:-http://192.168.1.21:8080}"
INSTALL_DIR="/opt/go2rtc-control"
ETC_DIR="/etc/go2rtc-control"

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "Utilisateur système introuvable : ${SERVICE_USER}" >&2
  exit 1
fi
if [[ ! -r "${CONFIG_PATH}" ]]; then
  echo "Fichier de configuration go2rtc introuvable ou illisible : ${CONFIG_PATH}" >&2
  echo "Définis GO2RTC_CONFIG avant de lancer le script si nécessaire." >&2
  exit 1
fi

apt-get update
apt-get install -y python3-yaml

install -d -o root -g "${SERVICE_USER}" -m 0750 "${INSTALL_DIR}" "${ETC_DIR}"
install -o root -g root -m 0644 "${SCRIPT_DIR}/server.py" "${INSTALL_DIR}/server.py"
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
TOKEN_FILE=${ETC_DIR}/token
DASHBOARD_ORIGIN=${DASHBOARD_ORIGIN}
CONTROL_HOST=0.0.0.0
CONTROL_PORT=1985
EOF
  chown root:"${SERVICE_USER}" "${ETC_DIR}/go2rtc-control.env"
  chmod 0640 "${ETC_DIR}/go2rtc-control.env"
fi

systemctl daemon-reload
systemctl enable --now go2rtc-control.service

echo
echo "Service installé et démarré."
echo "Configuration : ${ETC_DIR}/go2rtc-control.env"
echo "Jeton à saisir dans les paramètres du tableau de bord :"
cat "${ETC_DIR}/token"
echo
echo "Vérifie que le port TCP 1985 reste limité à ton réseau local."
