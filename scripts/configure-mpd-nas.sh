#!/bin/sh
# Run locally on novin with sudo. Credentials stay on the server and are never printed.
set -eu

APP_DIR=/home/whilser/NovinMusicService
ENV_FILE="$APP_DIR/.env"
MPD_CONFIG=/etc/mpd.conf
MOUNT_POINT=/mnt/novin-music
CREDENTIALS_FILE=/etc/novin-mpd-smb.credentials
HOST=${1:?Usage: sudo $0 <nas-host> <share>}
SHARE=${2:?Usage: sudo $0 <nas-host> <share>}

if [ ! -r "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi
if ! command -v mount.cifs >/dev/null 2>&1; then
  echo "cifs-utils is required: sudo apt install cifs-utils" >&2
  exit 1
fi

env_value() {
  awk -v key="$1" 'index($0, key "=") == 1 { print substr($0, length(key) + 2); exit }' "$ENV_FILE"
}

USERNAME=$(env_value SMB_USERNAME)
PASSWORD=$(env_value SMB_PASSWORD)
if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
  echo "SMB_USERNAME and SMB_PASSWORD must be set in $ENV_FILE" >&2
  exit 1
fi

umask 077
printf 'username=%s\npassword=%s\n' "$USERNAME" "$PASSWORD" > "$CREDENTIALS_FILE"
chmod 600 "$CREDENTIALS_FILE"

mkdir -p "$MOUNT_POINT"
FSTAB_LINE="//$HOST/$SHARE $MOUNT_POINT cifs credentials=$CREDENTIALS_FILE,iocharset=utf8,vers=3.0,ro,nofail,_netdev,x-systemd.automount 0 0"
grep -Fqx "$FSTAB_LINE" /etc/fstab || printf '%s\n' "$FSTAB_LINE" >> /etc/fstab

if mountpoint -q "$MOUNT_POINT"; then
  umount "$MOUNT_POINT"
fi
mount "$MOUNT_POINT"

BACKUP="$MPD_CONFIG.novin-music.$(date +%Y%m%d%H%M%S).bak"
cp "$MPD_CONFIG" "$BACKUP"
if grep -q '^[[:space:]]*music_directory[[:space:]]' "$MPD_CONFIG"; then
  sed -i 's|^[[:space:]]*music_directory[[:space:]].*$|music_directory "/mnt/novin-music"|' "$MPD_CONFIG"
else
  printf '\nmusic_directory "/mnt/novin-music"\n' >> "$MPD_CONFIG"
fi

systemctl restart mpd
mpc update
echo "MPD now uses $MOUNT_POINT. Backup: $BACKUP"
