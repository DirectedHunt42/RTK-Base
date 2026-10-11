#!/bin/bash
set -e

echo "========================================"
echo "  RTK-Base Setup"
echo "========================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run with sudo:  sudo ./setup.sh"
  exit 1
fi
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

DASHBOARD_USER="${SUDO_USER:-pi}"
if ! id "$DASHBOARD_USER" >/dev/null 2>&1; then
  DASHBOARD_USER="$(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 && $6 ~ /^\/home\// { print $1; exit }')"
fi
if [ -z "$DASHBOARD_USER" ] || ! id "$DASHBOARD_USER" >/dev/null 2>&1; then
  echo "Could not find a non-root account for the dashboard service" >&2
  exit 1
fi

echo "[1/7] Installing dependencies..."
apt update
mapfile -t APT_PACKAGES < <(python3 -c 'import json; print("\n".join(json.load(open("packages.json"))["apt"]))')
if [ "${#APT_PACKAGES[@]}" -eq 0 ]; then
  echo "No APT packages found in packages.json" >&2
  exit 1
fi
apt install -y "${APT_PACKAGES[@]}"

if [ ! -x /usr/bin/str2str ]; then
  echo "RTKLIB package installed but /usr/bin/str2str is missing" >&2
  exit 1
fi

echo "[2/7] Detecting receiver and creating directories..."
GNSS_DEVICE=""
for candidate in /dev/serial/by-id/*u-blox*; do
  if [ -e "$candidate" ]; then
    GNSS_DEVICE="$candidate"
    break
  fi
done
if [ -z "$GNSS_DEVICE" ]; then
  for candidate in /dev/serial/by-id/*; do
    if [ -e "$candidate" ]; then
      GNSS_DEVICE="$candidate"
      break
    fi
  done
fi
if [ -z "$GNSS_DEVICE" ]; then
  for candidate in /dev/ttyACM* /dev/ttyUSB*; do
    if [ -e "$candidate" ]; then
      GNSS_DEVICE="$candidate"
      break
    fi
  done
fi
if [ -z "$GNSS_DEVICE" ]; then
  echo "No GNSS serial receiver found. Connect it and rerun setup." >&2
  exit 1
fi
printf 'RTK_BASE_GNSS_DEVICE=%s\n' "$GNSS_DEVICE" > /etc/default/rtk-base
echo "Using GNSS receiver: $GNSS_DEVICE"
echo "Dashboard service account: $DASHBOARD_USER"
mkdir -p /opt/rtk-base
cp -r dashboard /opt/rtk-base/
cp -r scripts /opt/rtk-base/
find /opt/rtk-base/scripts -type f -name "*.sh" -exec chmod +x {} +

echo "[3/7] Installing systemd services and web proxy..."
cp services/systemd/str2str.service /etc/systemd/system/
sed "s/^User=pi$/User=$DASHBOARD_USER/" services/systemd/rtk-dashboard.service > /etc/systemd/system/rtk-dashboard.service
cp services/systemd/rtk-gpsd.service /etc/systemd/system/
cp services/nginx/rtk-base.conf /etc/nginx/sites-available/rtk-base
install -o root -g root -m 0755 scripts/receiver/set_mode.sh /usr/local/sbin/rtk-base-set-mode
install -o root -g root -m 0755 scripts/receiver/start_str2str.py /usr/local/sbin/rtk-base-start-str2str
install -o root -g root -m 0755 scripts/maintenance/update.sh /usr/local/sbin/rtk-base-update
install -o root -g root -m 0755 scripts/maintenance/download_file.sh /usr/local/sbin/rtk-base-download-file
printf '%s\n' "$REPO_DIR" > /etc/rtk-base-update-repo
chmod 0644 /etc/rtk-base-update-repo
printf '%s\n' "$DASHBOARD_USER ALL=(root) NOPASSWD: /usr/local/sbin/rtk-base-set-mode corrections, /usr/local/sbin/rtk-base-set-mode telemetry, /usr/local/sbin/rtk-base-update, /usr/local/sbin/rtk-base-update --approve-apt-upgrade, /usr/local/sbin/rtk-base-update --decline-apt-upgrade, /usr/local/sbin/rtk-base-download-file, /usr/bin/systemctl reboot" > /etc/sudoers.d/rtk-base-dashboard
chmod 0440 /etc/sudoers.d/rtk-base-dashboard
visudo -cf /etc/sudoers.d/rtk-base-dashboard
ln -sf /etc/nginx/sites-available/rtk-base /etc/nginx/sites-enabled/rtk-base
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx
systemctl disable --now gpsd.socket gpsd.service 2>/dev/null || true

echo "[4/7] Reloading systemd..."
systemctl daemon-reload

echo "[5/7] Enabling and starting services..."
systemctl enable str2str
systemctl enable rtk-dashboard
systemctl restart str2str
systemctl restart rtk-dashboard

echo "[6/7] Checking status..."
sleep 2
echo ""
systemctl --no-pager --full status str2str || true
echo ""
systemctl --no-pager --full status rtk-dashboard || true
echo ""
echo "Listening ports:"
ss -ltnp | grep -E ":$(cat /var/lib/rtk-base/stream-port)([[:space:]]|$)|:80([[:space:]]|$)|:8080([[:space:]]|$)" || true

echo ""
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo "RTCM stream : tcp://$(hostname -I | awk '{print $1}'):$(cat /var/lib/rtk-base/stream-port)"
echo "Dashboard   : http://$(hostname -I | awk '{print $1}')"
echo ""
