#!/bin/bash
set -Eeuo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Run this script through sudo" >&2
  exit 1
fi
LOG_FILE=/var/log/rtk-base-update.log
STATUS_FILE=/var/lib/rtk-base/update-status
LOCK_FILE=/run/lock/rtk-base-update.lock
START_LOCK_FILE=/run/lock/rtk-base-update-start.lock
mkdir -p /var/lib/rtk-base

set_status() {
  printf '%s\n' "$1" > "$STATUS_FILE"
  chmod 0644 "$STATUS_FILE"
}

if [ "${1:-}" != "--run" ]; then
  if [ "$#" -ne 0 ]; then
    echo "This script does not accept arguments" >&2
    exit 2
  fi
  exec 8>"$START_LOCK_FILE"
  if ! flock -n 8; then
    echo "An RTK-Base update is already starting" >&2
    exit 1
  fi
  current_status="$(cat "$STATUS_FILE" 2>/dev/null || true)"
  case "$current_status" in
    "Starting RTK-Base update"*|"Updating RTK-Base"*)
      unit_state="$(/usr/bin/systemctl show --property=ActiveState --value rtk-base-update.service 2>/dev/null || true)"
      case "$unit_state" in
        active|activating|deactivating|reloading)
          echo "An RTK-Base update is already running" >&2
          exit 1
          ;;
      esac
      if ! flock -n "$LOCK_FILE" -c true; then
        echo "An RTK-Base update is already running" >&2
        exit 1
      fi
      ;;
  esac
  : > "$LOG_FILE"
  chmod 0644 "$LOG_FILE"
  set_status "Starting RTK-Base update..."
  if ! /usr/bin/systemd-run --quiet --collect --unit=rtk-base-update \
      --setenv="SUDO_USER=${SUDO_USER:-}" \
      /usr/local/sbin/rtk-base-update --run >>"$LOG_FILE" 2>&1; then
    set_status "Update failed to start. See /var/log/rtk-base-update.log."
    exit 1
  fi
  exit 0
fi

if [ "$#" -ne 1 ]; then
  echo "Invalid updater invocation" >&2
  exit 2
fi

REPO_DIR="$(cat /etc/rtk-base-update-repo)"
exec >>"$LOG_FILE" 2>&1

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "An RTK-Base update is already running" >&2
  exit 1
fi
: > "$LOG_FILE"
chmod 0644 "$LOG_FILE"

trap 'result=$?; if [ "$result" -ne 0 ]; then set_status "Update failed (exit $result). See /var/log/rtk-base-update.log."; fi' EXIT
set_status "Updating RTK-Base..."

if [ ! -d "$REPO_DIR/.git" ] || [ ! -f "$REPO_DIR/setup.sh" ]; then
  echo "RTK-Base repository not found at $REPO_DIR" >&2
  exit 1
fi

REPO_OWNER="$(stat -c '%U' "$REPO_DIR")"
run_as_repo_owner() {
  if [ "$REPO_OWNER" = root ]; then
    "$@"
  else
    runuser -u "$REPO_OWNER" -- "$@"
  fi
}

echo "Resetting tracked changes in $REPO_DIR"
run_as_repo_owner git -C "$REPO_DIR" reset --hard
echo "Pulling updates"
run_as_repo_owner git -C "$REPO_DIR" pull

chmod +x "$REPO_DIR/setup.sh"
echo "Running setup"
cd "$REPO_DIR"
./setup.sh

set_status "Update complete."
trap - EXIT
