#!/bin/bash
echo "=== RTK-Base Status ==="
echo ""
echo "str2str service:"
systemctl is-active str2str
echo ""
echo "Dashboard service:"
systemctl is-active rtk-dashboard
echo ""
echo "Listening ports:"
RTCM_PORT=$(cat /var/lib/rtk-base/stream-port 2>/dev/null || echo 2101)
ss -ltnp | grep -E ":${RTCM_PORT}|:2948|:8080" || echo "None"
echo "RTCM output port: ${RTCM_PORT}"
echo ""
echo "Recent str2str log:"
journalctl -u str2str -n 6 --no-pager -o cat
