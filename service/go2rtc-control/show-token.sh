#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TOKEN_FILE+x}" && -r /etc/go2rtc-control/go2rtc-control.env ]]; then
  configured_token_file="$(sed -n 's/^[[:space:]]*TOKEN_FILE[[:space:]]*=[[:space:]]*//p' /etc/go2rtc-control/go2rtc-control.env | tail -n 1)"
  configured_token_file="${configured_token_file%\"}"
  configured_token_file="${configured_token_file#\"}"
  configured_token_file="${configured_token_file%\'}"
  configured_token_file="${configured_token_file#\'}"
  if [[ -n "${configured_token_file}" ]]; then
    TOKEN_FILE="${configured_token_file}"
  fi
fi
TOKEN_FILE="${TOKEN_FILE:-/etc/go2rtc-control/token}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Lance cette commande avec sudo : sudo go2rtc-control-show-token" >&2
  exit 1
fi

if [[ ! -t 1 ]]; then
  echo "Affichage refusé : la sortie doit être un terminal interactif." >&2
  exit 1
fi

if [[ ! -f "${TOKEN_FILE}" || -L "${TOKEN_FILE}" || ! -r "${TOKEN_FILE}" ]]; then
  echo "Fichier de jeton absent, illisible ou non régulier : ${TOKEN_FILE}" >&2
  exit 1
fi

owner="$(stat -c '%u' -- "${TOKEN_FILE}")"
mode="$(stat -c '%a' -- "${TOKEN_FILE}")"
if [[ "${owner}" != "0" ]] || (( (8#${mode} & 0037) != 0 )); then
  echo "Permissions incorrectes : le fichier doit appartenir à root et ne pas être accessible en écriture/exécution au groupe ni accessible aux autres." >&2
  exit 1
fi

mapfile -t token_lines < "${TOKEN_FILE}"
if [[ "${#token_lines[@]}" -ne 1 || -z "${token_lines[0]}" ]]; then
  echo "Format de jeton invalide : une seule ligne non vide est attendue." >&2
  exit 1
fi

echo "ATTENTION : le jeton ci-dessous est un secret d'accès à l'API."
echo "Ne le partage pas et ne le copie pas dans un journal ou une capture d'écran."
printf '%s\n' "${token_lines[0]}"
