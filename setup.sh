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

echo "[1/7] Installing dependencies..."
apt update
apt install -y python3-flask python3-psutil nginx gpsd sudo

echo "[2/7] Creating directories..."
mkdir -p /opt/rtk-base
cp -r dashboard /opt/rtk-base/
cp -r scripts /opt/rtk-base/
chmod +x /opt/rtk-base/scripts/*.sh 2>/dev/null || true

echo "[3/7] Installing systemd services and web proxy..."
cp services/str2str.service /etc/systemd/system/
cp services/rtk-dashboard.service /etc/systemd/system/
cp services/rtk-gpsd.service /etc/systemd/system/
cp services/rtk-base-nginx.conf /etc/nginx/sites-available/rtk-base
install -o root -g root -m 0755 scripts/set_mode.sh /usr/local/sbin/rtk-base-set-mode
printf '%s\n' 'pi ALL=(root) NOPASSWD: /usr/local/sbin/rtk-base-set-mode corrections, /usr/local/sbin/rtk-base-set-mode telemetry' > /etc/sudoers.d/rtk-base-dashboard
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
ss -ltnp | grep -E '2101|:80|8080' || true

echo ""
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo "RTCM stream : tcp://$(hostname -I | awk '{print $1}'):2101"
echo "Dashboard   : http://$(hostname -I | awk '{print $1}')"
echo ""
