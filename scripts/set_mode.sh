#!/bin/bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Must be run as root" >&2
  exit 1
fi

case "${1:-}" in
  corrections)
    systemctl stop rtk-gpsd.service
    systemctl restart str2str.service
    ;;
  telemetry)
    systemctl stop str2str.service
    systemctl start rtk-gpsd.service
    ;;
  *)
    echo "Usage: set_mode.sh {corrections|telemetry}" >&2
    exit 2
    ;;
esac
