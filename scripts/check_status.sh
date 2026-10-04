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
ss -ltnp | grep -E '2101|2948|8080' || echo "None"
echo ""
echo "Recent str2str log:"
journalctl -u str2str -n 6 --no-pager -o cat
