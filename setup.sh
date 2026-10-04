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
apt install -y python3-flask python3-psutil nginx gpsd sudo iw iproute2 usbutils rtklib

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
chmod +x /opt/rtk-base/scripts/*.sh 2>/dev/null || true

echo "[3/7] Installing systemd services and web proxy..."
cp services/str2str.service /etc/systemd/system/
sed "s/^User=pi$/User=$DASHBOARD_USER/" services/rtk-dashboard.service > /etc/systemd/system/rtk-dashboard.service
cp services/rtk-gpsd.service /etc/systemd/system/
cp services/rtk-base-nginx.conf /etc/nginx/sites-available/rtk-base
install -o root -g root -m 0755 scripts/set_mode.sh /usr/local/sbin/rtk-base-set-mode
install -o root -g root -m 0755 scripts/start_str2str.py /usr/local/sbin/rtk-base-start-str2str
printf '%s\n' "$DASHBOARD_USER ALL=(root) NOPASSWD: /usr/local/sbin/rtk-base-set-mode corrections, /usr/local/sbin/rtk-base-set-mode telemetry" > /etc/sudoers.d/rtk-base-dashboard
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
