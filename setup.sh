bash
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

echo "[1/6] Installing dependencies..."
apt update
apt install -y python3-flask python3-psutil

echo "[2/6] Creating directories..."
mkdir -p /opt/rtk-base
cp -r dashboard /opt/rtk-base/
cp -r scripts /opt/rtk-base/
chmod +x /opt/rtk-base/scripts/*.sh 2>/dev/null || true

echo "[3/6] Installing systemd services..."
cp services/str2str.service /etc/systemd/system/
cp services/rtk-dashboard.service /etc/systemd/system/

echo "[4/6] Reloading systemd..."
systemctl daemon-reload

echo "[5/6] Enabling and starting services..."
systemctl enable str2str
systemctl enable rtk-dashboard
systemctl restart str2str
systemctl restart rtk-dashboard

echo "[6/6] Checking status..."
sleep 2
echo ""
systemctl --no-pager --full status str2str || true
echo ""
systemctl --no-pager --full status rtk-dashboard || true
echo ""
echo "Listening ports:"
ss -ltnp | grep -E '2101|8080' || true

echo ""
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo "RTCM stream : tcp://$(hostname -I | awk '{print $1}'):2101"
echo "Dashboard   : http://$(hostname -I | awk '{print $1}'):8080"
echo ""