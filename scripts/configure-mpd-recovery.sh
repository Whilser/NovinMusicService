#!/bin/sh
# Install a local systemd watchdog for MPD and increase its control-socket queue.
set -eu

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd is required" >&2
  exit 1
fi

# This MPD installation binds port 6600 itself.  Running its optional socket
# activation unit at the same time races for that port, so keep one listener.
sudo systemctl disable --now mpd.socket || true
printf '%s\n' '#!/bin/sh' 'set -eu' 'if ! /usr/bin/python3 -c "import socket; s=socket.create_connection((\"127.0.0.1\",6600),2); s.settimeout(2); assert s.recv(32).startswith(b\"OK MPD \"); s.close()"; then systemctl restart mpd; fi' | sudo tee /usr/local/sbin/novin-mpd-watchdog >/dev/null
sudo chmod 755 /usr/local/sbin/novin-mpd-watchdog
printf '%s\n' '[Unit]' 'Description=Recover Novin MPD control socket when it stops responding' '' '[Service]' 'Type=oneshot' 'ExecStart=/usr/local/sbin/novin-mpd-watchdog' | sudo tee /etc/systemd/system/novin-mpd-watchdog.service >/dev/null
printf '%s\n' '[Unit]' 'Description=Run Novin MPD recovery check every minute' '' '[Timer]' 'OnBootSec=1min' 'OnUnitActiveSec=1min' 'Persistent=true' '' '[Install]' 'WantedBy=timers.target' | sudo tee /etc/systemd/system/novin-mpd-watchdog.timer >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now novin-mpd-watchdog.timer
sudo systemctl restart mpd
sudo systemctl start novin-mpd-watchdog.service
echo "MPD recovery watchdog is enabled."
