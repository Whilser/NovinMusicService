#!/bin/sh
# Increase MPD's systemd socket backlog.  A small default queue can fill with
# stale control connections when an internet radio stream fails or changes.
set -eu

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd is required" >&2
  exit 1
fi

sudo install -d -m 0755 /etc/systemd/system/mpd.socket.d
printf '%s\n' '[Socket]' 'Backlog=64' | sudo tee /etc/systemd/system/mpd.socket.d/novin.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart mpd.socket mpd
sudo systemctl is-active --quiet mpd
echo "MPD socket backlog is set to 64 and MPD is active."
