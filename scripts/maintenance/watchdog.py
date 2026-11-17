#!/usr/bin/env python3
"""Optional recovery watchdog for the RTK-Base dashboard service."""

from __future__ import annotations

import json
import html
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE_DIR = Path("/var/lib/rtk-base/watchdog")
STATE_FILE = STATE_DIR / "state.json"
ERROR_FLAG = STATE_DIR / "error-page"
LOG_FILE = STATE_DIR / "watchdog.log"
ERROR_PAGE_TEMPLATE = Path("/opt/rtk-base/dashboard/static/rtk-base-error.html")
ERROR_PAGE_TARGET = Path("/var/www/rtk-base-error.html")
ERROR_MESSAGE_PLACEHOLDER = "<p>The dashboard service is unavailable or is restarting.</p>"
SERVICE = "rtk-dashboard.service"
WINDOW_SECONDS = 300
POLL_SECONDS = 5
STABLE_RESET_SECONDS = 300
REBOOT_GRACE_SECONDS = 120


def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/systemctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"


def restart_count() -> int:
    result = systemctl("show", "--property=NRestarts", "--value", SERVICE)
    try:
        return max(0, int(result.stdout.strip())) if result.returncode == 0 else 0
    except ValueError:
        return 0


def service_active() -> bool:
    return systemctl("is-active", "--quiet", SERVICE).returncode == 0


def load_state() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            json.dump(state, temp_file, separators=(",", ":"))
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, STATE_FILE)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def log_event(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S %z')} {message}\n"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as log_file:
            log_file.write(line)
        os.chmod(LOG_FILE, 0o644)
    except OSError:
        pass
    print(message, flush=True)


def clear_recovery_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for path in (STATE_FILE, ERROR_FLAG):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        ERROR_PAGE_TARGET.write_text(ERROR_PAGE_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(ERROR_PAGE_TARGET, 0o644)
    except OSError:
        pass


def set_error_page(state: dict, reason: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ERROR_FLAG.write_text(reason + "\n", encoding="utf-8")
    os.chmod(ERROR_FLAG, 0o644)
    try:
        template = ERROR_PAGE_TEMPLATE.read_text(encoding="utf-8")
        rendered = template.replace(ERROR_MESSAGE_PLACEHOLDER, f"<p>{html.escape(reason)}</p>")
        ERROR_PAGE_TARGET.write_text(rendered, encoding="utf-8")
        os.chmod(ERROR_PAGE_TARGET, 0o644)
    except OSError as err:
        log_event(f"Could not update the static error page: {err}")
    log_event(reason)
    state["error_page"] = True
    state["error_reason"] = reason
    save_state(state)


def control(action: str) -> int:
    if os.geteuid() != 0:
        print("Run this command through sudo", file=sys.stderr)
        return 1
    if action == "status":
        enabled = systemctl("is-enabled", "--quiet", "rtk-base-watchdog.service").returncode == 0
        active = systemctl("is-active", "--quiet", "rtk-base-watchdog.service").returncode == 0
        state = load_state()
        print(json.dumps({
            "enabled": enabled,
            "active": active,
            "error_page": ERROR_FLAG.exists(),
            "recent_restarts": len(state.get("restart_events", [])),
        }))
        return 0

    if action == "enable":
        clear_recovery_state()
        result = systemctl("enable", "--now", "rtk-base-watchdog.service")
    elif action == "disable":
        result = systemctl("disable", "--now", "rtk-base-watchdog.service")
        if result.returncode == 0:
            clear_recovery_state()
    else:
        print("Usage: rtk-base-watchdog {enable|disable|status|watch}", file=sys.stderr)
        return 2

    if result.returncode != 0:
        print(result.stderr.strip() or f"systemctl {action} failed", file=sys.stderr)
        return result.returncode or 1
    return 0


def run_watchdog() -> int:
    if os.geteuid() != 0:
        print("The watchdog service must run as root", file=sys.stderr)
        return 1

    state = load_state()
    current_boot = boot_id()
    current_restarts = restart_count()
    now = time.time()

    if not state:
        state = {
            "boot_id": current_boot,
            "last_restarts": current_restarts,
            "restart_events": [],
            "healthy_since": now if service_active() else None,
            "reboot_attempted": False,
            "after_reboot": False,
        }
        save_state(state)

    while True:
        now = time.time()
        current_boot = boot_id()
        current_restarts = restart_count()
        state = load_state()

        if ERROR_FLAG.exists():
            time.sleep(POLL_SECONDS)
            continue

        if state.get("boot_id") != current_boot:
            had_watchdog_reboot = bool(state.get("reboot_attempted"))
            state["boot_id"] = current_boot
            state["restart_events"] = []
            state["healthy_since"] = None
            if had_watchdog_reboot:
                state["after_reboot"] = True
                state["last_restarts"] = 0
            else:
                state["after_reboot"] = False
                state["last_restarts"] = current_restarts
            save_state(state)

        last_restarts = int(state.get("last_restarts", current_restarts))
        if current_restarts > last_restarts:
            new_restarts = current_restarts - last_restarts
            state.setdefault("restart_events", []).extend([now] * new_restarts)
            log_event(f"Observed {new_restarts} automatic dashboard service restart(s).")
            state["healthy_since"] = None
        state["last_restarts"] = current_restarts
        state["restart_events"] = [
            event for event in state.get("restart_events", [])
            if isinstance(event, (int, float)) and 0 <= now - event <= WINDOW_SECONDS
        ]

        if service_active():
            if state.get("healthy_since") is None:
                state["healthy_since"] = now
            if now - state["healthy_since"] >= STABLE_RESET_SECONDS:
                state["restart_events"] = []
                state["reboot_attempted"] = False
                state["reboot_requested_at"] = None
                state["reboot_boot_id"] = None
                state["after_reboot"] = False
        else:
            state["healthy_since"] = None

        restart_events = state["restart_events"]
        if len(restart_events) >= 3:
            if state.get("after_reboot"):
                set_error_page(state, "The dashboard continued restarting after the watchdog rebooted the Pi.")
                time.sleep(POLL_SECONDS)
                continue
            if not state.get("reboot_attempted"):
                state["reboot_attempted"] = True
                state["reboot_requested_at"] = now
                state["reboot_boot_id"] = current_boot
                save_state(state)
                log_event("Three dashboard restarts occurred within five minutes; requesting a Pi reboot.")
                systemctl("reboot")
            elif (
                state.get("reboot_boot_id") == current_boot
                and now - float(state.get("reboot_requested_at") or now) >= REBOOT_GRACE_SECONDS
            ):
                set_error_page(state, "The watchdog could not complete the requested Pi reboot.")
                time.sleep(POLL_SECONDS)
                continue

        save_state(state)
        time.sleep(POLL_SECONDS)


def main() -> int:
    args = sys.argv[1:]
    if args == ["watch"]:
        return run_watchdog()
    if len(args) == 1:
        return control(args[0])
    print("Usage: rtk-base-watchdog {enable|disable|status|watch}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
