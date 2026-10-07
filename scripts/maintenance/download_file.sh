#!/bin/bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Run this script through sudo" >&2
  exit 1
fi
if [ "$#" -ne 1 ]; then
  echo "A known file ID is required" >&2
  exit 2
fi

case "$1" in
  str2str-log)
    exec /usr/bin/journalctl -u str2str.service -n 500 --no-pager -o short-iso
    ;;
  dashboard-log)
    exec /usr/bin/journalctl -u rtk-dashboard.service -n 500 --no-pager -o short-iso
    ;;
  gpsd-log)
    exec /usr/bin/journalctl -u rtk-gpsd.service -n 500 --no-pager -o short-iso
    ;;
  nginx-error-log)
    exec /usr/bin/tail -n 1000 /var/log/nginx/error.log
    ;;
  nginx-access-log)
    exec /usr/bin/tail -n 1000 /var/log/nginx/access.log
    ;;
  update-log)
    exec /usr/bin/tail -n 2000 /var/log/rtk-base-update.log
    ;;
  gnss-config)
    exec /usr/bin/cat /etc/default/rtk-base
    ;;
  stream-port)
    exec /usr/bin/cat /var/lib/rtk-base/stream-port
    ;;
  str2str-service)
    exec /usr/bin/cat /etc/systemd/system/str2str.service
    ;;
  dashboard-service)
    exec /usr/bin/cat /etc/systemd/system/rtk-dashboard.service
    ;;
  gpsd-service)
    exec /usr/bin/cat /etc/systemd/system/rtk-gpsd.service
    ;;
  nginx-config)
    exec /usr/bin/cat /etc/nginx/sites-available/rtk-base
    ;;
  *)
    echo "Unknown file ID" >&2
    exit 2
    ;;
esac
