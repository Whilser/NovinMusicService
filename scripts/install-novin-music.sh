#!/bin/sh
# Bootstrap Novin Music on a Debian/Ubuntu server.  Run from the repository
# checkout as the regular server user; the script asks for sudo only when needed.
set -eu

APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NAS_HOST=""
NAS_SHARE=""
USE_APPARMOR_OVERRIDE=false

usage() {
  printf '%s\n' \
    'Usage: ./scripts/install-novin-music.sh [options]' \
    '' \
    'Options:' \
    '  --nas-host HOST       Mount this SMB host for the system MPD after install.' \
    '  --nas-share SHARE     SMB share for --nas-host (requires credentials in .env).' \
    '  --apparmor-unconfined Use the optional Compose override only for a confirmed' \
    '                        AppArmor denial of mount.cifs.' \
    '  -h, --help            Show this help.' \
    '' \
    'The script preserves an existing .env. For a new file it copies .env.example;' \
    'fill SMB_USERNAME, SMB_PASSWORD and optionally MPD_PASSWORD before configuring' \
    'the NAS mount.'
}

compose() {
  if docker compose "$@" 2>/dev/null; then
    return 0
  fi
  sudo docker compose "$@"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --nas-host) NAS_HOST=${2:?--nas-host requires a value}; shift 2 ;;
    --nas-share) NAS_SHARE=${2:?--nas-share requires a value}; shift 2 ;;
    --apparmor-unconfined) USE_APPARMOR_OVERRIDE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if { [ -n "$NAS_HOST" ] && [ -z "$NAS_SHARE" ]; } || { [ -z "$NAS_HOST" ] && [ -n "$NAS_SHARE" ]; }; then
  echo "--nas-host and --nas-share must be used together" >&2
  exit 2
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Automatic dependency setup currently supports Debian/Ubuntu (apt-get)." >&2
  exit 1
fi

sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install --yes cifs-utils mpc curl ca-certificates
if ! compose version >/dev/null 2>&1; then
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install --yes docker.io docker-compose-plugin || \
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install --yes docker.io docker-compose-v2
  sudo systemctl enable --now docker
fi
if ! compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required but could not be installed automatically." >&2
  exit 1
fi

cd "$APP_DIR"
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created $APP_DIR/.env — add credentials before configuring an authenticated SMB share."
fi

COMPOSE_ARGS="-f docker-compose.yml"
if [ "$USE_APPARMOR_OVERRIDE" = true ]; then
  COMPOSE_ARGS="$COMPOSE_ARGS -f docker-compose.apparmor-unconfined.yml"
fi
# shellcheck disable=SC2086
compose $COMPOSE_ARGS config >/dev/null
# shellcheck disable=SC2086
compose $COMPOSE_ARGS up -d --build --force-recreate

PORT=$(awk -F= '$1 == "NOVIN_PORT" { print $2; exit }' .env)
PORT=${PORT:-8000}
curl --fail --silent --show-error "http://127.0.0.1:$PORT/api/health" >/dev/null
"$APP_DIR/scripts/configure-mpd-recovery.sh"

if [ -n "$NAS_HOST" ]; then
  sudo "$APP_DIR/scripts/configure-mpd-nas.sh" "$NAS_HOST" "$NAS_SHARE"
fi

echo "Novin Music is ready: http://$(hostname -f 2>/dev/null || hostname):$PORT"
