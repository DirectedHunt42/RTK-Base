#!/usr/bin/env python3
"""
RTK-Base Live Diagnostics Dashboard
Terminal-style web interface
"""

from flask import Flask, render_template_string, jsonify, request, Response
import json, subprocess, os, socket, psutil, time
from datetime import datetime, timedelta
from pathlib import Path

app = Flask(__name__)
APP_VERSION = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
GNSS_NAMES = {0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou", 4: "IMES", 5: "QZSS", 6: "GLONASS", 7: "NavIC"}

def run(cmd: str) -> str:
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""

def get_temp() -> str:
    t = run("vcgencmd measure_temp 2>/dev/null")
    if t:
        return t.replace("temp=", "").replace("'C", " °C")
    return "N/A"

def get_str2str():
    status = run("systemctl is-active str2str 2>/dev/null") or "unknown"
    journal = run("journalctl -u str2str -n 10 --no-pager -o cat 2>/dev/null")
    return status, journal

def get_rtcm_port() -> int:
    try:
        port = int(Path("/var/lib/rtk-base/stream-port").read_text(encoding="ascii").strip())
        return port if 1 <= port <= 65535 else 2101
    except (OSError, ValueError):
        return 2101

def get_listening() -> str:
    listeners = run("ss -ltnp")
    ports = {get_rtcm_port(), 80, 8080, 2948}
    return "\n".join(
        line for line in listeners.splitlines()
        if len(line.split()) > 3 and any(line.split()[3].endswith(f":{port}") for port in ports)
    )

def get_rtcm_client_count() -> int:
    connections = run(f"ss -Htn state established '( sport = :{get_rtcm_port()} )'")
    return len(connections.splitlines()) if connections else 0

def get_service_restarts() -> str:
    return run("systemctl show str2str.service -p NRestarts --value") or "0"

def get_stream_uptime() -> str:
    if run("systemctl is-active str2str.service 2>/dev/null") != "active":
        return "Not running"
    try:
        started = int(run("systemctl show str2str.service -p ActiveEnterTimestampMonotonic --value")) / 1_000_000
        return str(timedelta(seconds=max(0, int(time.monotonic() - started))))
    except (TypeError, ValueError, OSError):
        return "Unavailable"

def get_usb() -> str:
    return run("lsusb") or "No USB devices found"

def get_serial() -> str:
    return run("ls -l /dev/serial/by-id/ 2>/dev/null") or "No serial devices"

def get_default_interface():
    for route in run("ip -4 route show default").splitlines():
        parts = route.split()
        if parts and parts[0] == "default" and "dev" in parts:
            return parts[parts.index("dev") + 1]
    return None

def get_network() -> str:
    try:
        default_iface = get_default_interface()
        lines = []
        for name, addresses in psutil.net_if_addrs().items():
            stats = psutil.net_if_stats().get(name)
            ipv4 = [address.address for address in addresses
                    if address.family == socket.AF_INET and not address.address.startswith("127.")]
            if not ipv4:
                continue
            state = "up" if stats and stats.isup else "down"
            role = "default route" if name == default_iface else ""
            lines.append(f"{name}: {', '.join(ipv4)} [{state}] {role}".rstrip())
        return "\n".join(lines) or "No network interfaces with IPv4 addresses"
    except Exception:
        return "Network interface details unavailable"

def get_wifi_data() -> dict:
    wireless = [name for name in psutil.net_if_addrs()
                if os.path.isdir(f"/sys/class/net/{name}/wireless")]
    default_iface = get_default_interface()
    iface = default_iface if default_iface in wireless else next(
        (name for name in wireless if psutil.net_if_stats().get(name, None)
         and psutil.net_if_stats()[name].isup),
        wireless[0] if wireless else None
    )
    result = {"interface": iface or "—", "ssid": "—", "signal": "—",
              "quality": 0, "link": "No wireless interface detected"}
    if not iface:
        return result
    result["link"] = "Not connected"
    try:
        output = subprocess.check_output(
            ["iw", "dev", iface, "link"], text=True,
            stderr=subprocess.DEVNULL, timeout=1
        )
    except (OSError, subprocess.SubprocessError):
        result["link"] = "Wireless status unavailable (iw)"
        return result
    if output.strip().startswith("Not connected"):
        return result
    result["link"] = "Connected"
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("SSID:"):
            result["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("signal:"):
            fields = line.split()
            if len(fields) > 1:
                try:
                    dbm = float(fields[1])
                    result["signal"] = f"{dbm:.0f} dBm"
                    result["quality"] = max(0, min(100, round((dbm + 100) * 2)))
                except ValueError:
                    pass
        elif line.startswith("freq:"):
            result["frequency"] = f"{line.split(':', 1)[1].strip()} MHz"
        elif line.startswith("tx bitrate:"):
            result["bitrate"] = line.split(":", 1)[1].strip()
    return result

def get_network_traffic() -> dict:
    iface = get_default_interface()
    counters = psutil.net_io_counters(pernic=True).get(iface) if iface else None
    if not counters:
        return {"interface": iface or "—", "received": "—", "sent": "—"}
    return {
        "interface": iface,
        "received": f"{counters.bytes_recv / (1024 ** 2):.1f} MiB",
        "sent": f"{counters.bytes_sent / (1024 ** 2):.1f} MiB",
    }

def satellite_label(satellite: dict) -> str:
    gnssid = satellite.get("gnssid")
    constellation = GNSS_NAMES.get(gnssid, f"GNSS{gnssid}") if gnssid is not None else "SV"
    satellite_id = satellite.get("svid", satellite.get("PRN", "?"))
    return f"{constellation} {satellite_id}"

def get_gps_data() -> dict:
    """Read optional GPSD telemetry without opening the receiver serial port."""
    result = {
        "source": "GPSD telemetry mode",
        "fix": "No GPSD data",
        "position": "—",
        "latitude": None,
        "longitude": None,
        "altitude": "—",
        "speed": "—",
        "satellites": "—",
        "satellite_detail": "",
        "satellite_data": [],
        "satellite_status": "Waiting for GPSD sky view",
        "hdop": "—",
        "pdop": "—",
        "accuracy": "—",
        "fix_time": "—",
    }
    try:
        with socket.create_connection(("127.0.0.1", 2948), timeout=0.5) as conn:
            conn.settimeout(1.0)
            conn.sendall(b'?WATCH={"enable":true,"json":true};?POLL;\n')
            stream = conn.makefile("r", encoding="utf-8", errors="replace")
            tpv = None
            sky = None
            sky_report_received = False
            poll_received = False
            for _ in range(30):
                try:
                    line = stream.readline()
                except socket.timeout:
                    break
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("class") == "TPV":
                    tpv = message
                elif message.get("class") == "SKY":
                    sky = message
                    sky_report_received = True
                elif message.get("class") == "POLL":
                    poll_received = True
                    polled_tpv = message.get("tpv") or []
                    polled_sky = message.get("sky") or []
                    if polled_tpv:
                        tpv = polled_tpv[-1]
                    if polled_sky:
                        sky = polled_sky[-1]
                        sky_report_received = True
                if tpv and sky and (sky.get("satellites") or poll_received):
                    break
                if tpv and poll_received:
                    break
            if tpv or sky:
                mode = (tpv or {}).get("mode", 0)
                result["fix"] = {0: "No fix", 1: "No fix", 2: "2D fix", 3: "3D fix"}.get(mode, f"Mode {mode}")
                if tpv and "lat" in tpv and "lon" in tpv:
                    result["latitude"] = tpv["lat"]
                    result["longitude"] = tpv["lon"]
                    result["position"] = f"{tpv['lat']:.6f}, {tpv['lon']:.6f}"
                if tpv and "alt" in tpv:
                    result["altitude"] = f"{tpv['alt']:.1f} m"
                if tpv and "speed" in tpv:
                    result["speed"] = f"{tpv['speed']:.2f} m/s"
                if tpv and "eph" in tpv:
                    result["accuracy"] = f"~{tpv['eph']:.1f} m (GPSD estimate)"
                if tpv and tpv.get("time"):
                    result["fix_time"] = str(tpv["time"])
                satellites = (sky or {}).get("satellites", [])
                if sky and sky.get("hdop") is not None:
                    result["hdop"] = f"{sky['hdop']:.2f}"
                if sky and sky.get("pdop") is not None:
                    result["pdop"] = f"{sky['pdop']:.2f}"
                used = [sat for sat in satellites if sat.get("used")]
                result["satellites"] = f"{len(used)} used / {len(satellites)} visible"
                if satellites:
                    result["satellite_status"] = "GPSD sky view received"
                elif sky_report_received:
                    result["satellite_status"] = "GPSD sent a SKY report with no satellite entries"
                else:
                    result["satellite_status"] = "No SKY report from GPSD; check receiver satellite output"
                result["satellite_data"] = [
                    {
                        "id": satellite_label(sat),
                        "used": bool(sat.get("used")),
                        "signal": sat.get("ss"),
                        "azimuth": sat.get("az"),
                        "elevation": sat.get("el"),
                    }
                    for sat in satellites
                ]
                if satellites:
                    result["satellite_detail"] = "\n".join(
                        f"{'USED ' if sat.get('used') else ''}"
                        f"{satellite_label(sat)}: "
                        f"SNR {sat.get('ss', '—')} dB-Hz"
                        for sat in satellites
                    )
                return result
    except (OSError, socket.timeout):
        pass
    result["source"] = "No GPSD telemetry; switch to GPS telemetry mode"
    return result

def get_mode() -> str:
    if run("systemctl is-active rtk-gpsd.service 2>/dev/null") == "active":
        return "telemetry"
    if run("systemctl is-active str2str.service 2>/dev/null") == "active":
        return "corrections"
    return "stopped"

def get_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
        return str(timedelta(seconds=int(seconds)))
    except Exception:
        return "N/A"

def get_update_status() -> str:
    try:
        status_path = Path("/var/lib/rtk-base/update-status")
        status = status_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "Ready to update."
    if status.startswith(("Starting RTK-Base update", "Updating RTK-Base")):
        try:
            status_age = time.time() - status_path.stat().st_mtime
        except OSError:
            return status
        if status_age > 8 and not update_runner_active():
            return "Update complete. Dashboard restarted."
    return status

def update_runner_active() -> bool:
    try:
        unit = subprocess.run(
            ["/usr/bin/systemctl", "show", "--property=ActiveState", "--value", "rtk-base-update.service"],
            capture_output=True, text=True, timeout=1, check=False
        )
        if unit.stdout.strip() in ("active", "activating", "deactivating", "reloading"):
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        for process in psutil.process_iter(["cmdline"]):
            command = process.info.get("cmdline") or []
            if any(argument == "/usr/local/sbin/rtk-base-update" for argument in command):
                return True
    except (psutil.Error, OSError):
        pass
    return False

DOWNLOAD_ITEMS = [
    {"id": "str2str-log", "name": "RTCM stream log", "category": "Logs", "description": "Recent str2str service output", "filename": "str2str.log"},
    {"id": "dashboard-log", "name": "Dashboard log", "category": "Logs", "description": "Recent Flask dashboard service output", "filename": "rtk-dashboard.log"},
    {"id": "gpsd-log", "name": "GPSD log", "category": "Logs", "description": "Recent GPS telemetry service output", "filename": "rtk-gpsd.log"},
    {"id": "nginx-error-log", "name": "nginx error log", "category": "Logs", "description": "Last 1,000 nginx error log lines", "filename": "nginx-error.log"},
    {"id": "nginx-access-log", "name": "nginx access log", "category": "Logs", "description": "Last 1,000 nginx access log lines", "filename": "nginx-access.log"},
    {"id": "update-log", "name": "Update log", "category": "Logs", "description": "Recent update and setup output", "filename": "rtk-base-update.log"},
    {"id": "gnss-config", "name": "GNSS device config", "category": "Configuration", "description": "Selected receiver device path", "filename": "rtk-base.conf"},
    {"id": "stream-port", "name": "RTCM stream port", "category": "Configuration", "description": "Currently selected RTCM TCP port", "filename": "stream-port.txt"},
    {"id": "str2str-service", "name": "RTCM stream service", "category": "Configuration", "description": "Installed str2str systemd unit", "filename": "str2str.service"},
    {"id": "dashboard-service", "name": "Dashboard service", "category": "Configuration", "description": "Installed dashboard systemd unit", "filename": "rtk-dashboard.service"},
    {"id": "gpsd-service", "name": "GPSD service", "category": "Configuration", "description": "Installed GPSD systemd unit", "filename": "rtk-gpsd.service"},
    {"id": "nginx-config", "name": "nginx site config", "category": "Configuration", "description": "Installed dashboard reverse proxy config", "filename": "rtk-base-nginx.conf"},
]

REPO_ASSOCIATIONS = [
    {"source": "dashboard/", "target": "/opt/rtk-base/dashboard/"},
    {"source": "scripts/", "target": "/opt/rtk-base/scripts/"},
    {"source": "scripts/set_mode.sh", "target": "/usr/local/sbin/rtk-base-set-mode"},
    {"source": "scripts/start_str2str.py", "target": "/usr/local/sbin/rtk-base-start-str2str"},
    {"source": "scripts/update.sh", "target": "/usr/local/sbin/rtk-base-update"},
    {"source": "scripts/download_file.sh", "target": "/usr/local/sbin/rtk-base-download-file"},
    {"source": "services/str2str.service", "target": "/etc/systemd/system/str2str.service"},
    {"source": "services/rtk-dashboard.service", "target": "/etc/systemd/system/rtk-dashboard.service"},
    {"source": "services/rtk-gpsd.service", "target": "/etc/systemd/system/rtk-gpsd.service"},
    {"source": "services/rtk-base-nginx.conf", "target": "/etc/nginx/sites-available/rtk-base"},
    {"source": "setup.sh", "target": "/etc/default/rtk-base", "kind": "generated"},
    {"source": "setup.sh", "target": "/etc/sudoers.d/rtk-base-dashboard", "kind": "generated"},
]

def render_repo_tree(paths, associations) -> str:
    tree = {}
    for path in paths:
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None

    lines = ["."]

    def render_node(node: dict, prefix: str = "", parent: str = "") -> None:
        entries = sorted(node.items(), key=lambda entry: (entry[1] is None, entry[0].casefold()))
        for index, (name, child) in enumerate(entries):
            last = index == len(entries) - 1
            branch = "└── " if last else "├── "
            path = f"{parent}/{name}" if parent else name
            is_dir = isinstance(child, dict)
            label = name + ("/" if is_dir else "")
            if not is_dir and path in associations:
                label += f"  →  {' | '.join(associations[path])}"
            lines.append(f"{prefix}{branch}{label}")
            if is_dir:
                render_node(child, prefix + ("    " if last else "│   "), path)

    render_node(tree)
    return "\n".join(lines)

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RTK-Base Dashboard</title>
<link rel="icon" type="image/svg+xml" href="{{ url_for('static', filename='favicon.svg') }}">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap');
  :root {
    color-scheme: dark;
    --bg: #0a0a0a;
    --card: #111111;
    --border: #1e1e1e;
    --green: #00ff9f;
    --amber: #ffb000;
    --red: #ff5555;
    --text: #d0d0d0;
    --dim: #666666;
  }
  * {
    scrollbar-width: thin;
    scrollbar-color: #28523f var(--bg);
  }
  *::-webkit-scrollbar {
    width: 10px;
    height: 10px;
  }
  *::-webkit-scrollbar-track {
    background: var(--bg);
  }
  *::-webkit-scrollbar-thumb {
    background: #28523f;
    border: 2px solid var(--bg);
    border-radius: 8px;
  }
  *::-webkit-scrollbar-thumb:hover {
    background: var(--green);
  }
  *::-webkit-scrollbar-corner {
    background: var(--bg);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    line-height: 1.5;
    padding: 24px;
    min-height: 100vh;
  }
  header {
    margin-bottom: 28px;
    position: relative;
    padding-right: 320px;
  }
  .header-actions {
    position: absolute;
    top: 4px;
    right: 0;
    display: grid;
    justify-items: end;
    gap: 4px;
  }
  .header-action-buttons { display: flex; gap: 7px; }
  .dashboard-action {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: #111;
    border: 1px solid #28523f;
    border-radius: 5px;
    cursor: pointer;
    font: inherit;
    font-weight: 600;
    padding: 8px 12px;
  }
  .dashboard-action img { width: 16px; height: 16px; }
  .dashboard-action:hover { background: #002211; border-color: var(--green); }
  .dashboard-action:disabled { cursor: wait; opacity: 0.55; }
  .update-button { color: var(--green); }
  .reboot-button { color: var(--red); border-color: #713333; }
  .reboot-button:hover { background: #3a1111; border-color: var(--red); }
  #action-message { color: var(--amber); font-size: 11px; text-align: right; }
  @media (max-width: 720px) {
    header { padding-right: 0; padding-top: 46px; }
    .header-actions { left: 0; right: auto; }
    #action-message { text-align: left; }
    h1 { font-size: 1.25rem; }
  }
  h1 {
    color: var(--green);
    font-size: 1.7rem;
    letter-spacing: 2px;
    margin-bottom: 4px;
  }
  .subtitle {
    color: var(--dim);
    font-size: 12px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr));
    grid-auto-rows: auto;
    gap: 18px;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
    display: flex;
    flex-direction: column;
    aspect-ratio: 1;
    overflow: auto;
  }
  .card h2 {
    color: var(--amber);
    font-size: 0.9rem;
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    text-transform: uppercase;
    letter-spacing: 1px;
    flex: 0 0 auto;
  }
  .card h2::before {
    display: inline-block;
    transform: rotate(90deg);
    transition: transform 0.2s ease;
    content: "▶";
    color: var(--green);
    font-size: 0.65rem;
  }
  pre {
    /* Keep diagnostic text panels within their card's available height. */
    white-space: pre-wrap;
    word-break: break-all;
    font-size: 12px;
    color: var(--text);
  }
  .scroll-fill { flex: 1 1 auto; min-height: 100px; overflow: auto; }
  .scroll-stack { display: flex; flex: 1 1 auto; min-height: 180px; flex-direction: column; gap: 12px; }
  .scroll-stack > .scroll-fill { min-height: 70px; }
  .card.collapsed > :not(h2) { display: none; }
  .card.collapsed {
    align-self: start;
    aspect-ratio: auto;
    min-height: 0;
    padding-bottom: 10px;
  }
  .card.collapsed h2 { margin-bottom: 0; }
  .card h2[role="button"] { cursor: pointer; user-select: none; }
  .card h2[role="button"]:focus-visible { outline: 1px solid var(--green); outline-offset: 4px; }
  .card.collapsed h2::before { transform: rotate(0deg); }
  .status {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.5px;
  }
  .status.ok { background: #002211; color: var(--green); }
  .status.fail { background: #330011; color: var(--red); }
  .metric {
    display: flex;
    justify-content: space-between;
    margin: 7px 0;
  }
  .metric span:last-child {
    color: var(--green);
    font-weight: 600;
  }
  .bar {
    height: 7px;
    background: #1a1a1a;
    border-radius: 4px;
    margin: 4px 0 12px 0;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #00cc7a, #00ff9f);
    border-radius: 4px;
    transition: width 0.6s ease;
  }
  .wifi-signal-display { display: flex; align-items: center; gap: 10px; margin: 10px 0; }
  .wifi-icon { width: 34px; height: 28px; overflow: visible; }
  .wifi-icon path, .wifi-icon circle { fill: none; stroke: #555; stroke-width: 3; stroke-linecap: round; }
  .wifi-icon .active { stroke: var(--green); }
  .wifi-icon circle { fill: #555; stroke: none; }
  .wifi-icon circle.active { fill: var(--green); }
  .mode-controls { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
  .mode-controls button {
    background: #111;
    border: 1px solid #28523f;
    border-radius: 5px;
    color: var(--green);
    cursor: pointer;
    font: inherit;
    padding: 7px 10px;
  }
  .mode-controls button:hover, .mode-controls button.active { background: #002211; border-color: var(--green); }
  .mode-controls button:disabled { cursor: wait; opacity: 0.55; }
  .mode-message { color: var(--amber); min-height: 1.5em; }
  #gps-map {
    height: 320px;
    width: 100%;
    background: #101713;
    border: 1px solid var(--border);
    border-radius: 6px;
    z-index: 0;
  }
  .map-note { color: var(--dim); font-size: 11px; margin-top: 8px; }
  .satellite-graphics { display: grid; flex: 1 1 auto; min-height: 240px; grid-template-columns: minmax(190px, 240px) 1fr; gap: 18px; align-items: center; }
  #satellite-sky { width: 100%; max-width: 240px; height: auto; }
  .sky-ring { fill: none; stroke: #28523f; stroke-width: 1; }
  .sky-cross { stroke: #1e3b2d; stroke-width: 1; }
  .sky-cardinal { fill: var(--dim); font: 10px 'JetBrains Mono', monospace; text-anchor: middle; }
  .sky-sat { fill: #666; stroke: #0a0a0a; stroke-width: 1.5; }
  .sky-sat.used { fill: var(--green); }
  .sky-label { fill: var(--text); font: 8px 'JetBrains Mono', monospace; text-anchor: middle; }
  .signal-list { display: grid; align-content: start; gap: 6px; flex: 1 1 auto; min-height: 220px; overflow: auto; }
  .signal-row { display: grid; grid-template-columns: 68px 1fr 52px; gap: 8px; align-items: center; font-size: 11px; }
  .signal-track { height: 7px; background: #1a1a1a; border-radius: 5px; overflow: hidden; }
  .signal-fill { height: 100%; background: #777; border-radius: inherit; }
  .signal-fill.used { background: var(--green); }
  .sat-cell { display: flex; align-items: end; gap: 2px; height: 18px; }
  .sat-cell i { display: block; width: 4px; background: #303030; border-radius: 1px 1px 0 0; }
  .sat-cell i:nth-child(1) { height: 5px; }
  .sat-cell i:nth-child(2) { height: 9px; }
  .sat-cell i:nth-child(3) { height: 13px; }
  .sat-cell i:nth-child(4) { height: 17px; }
  .sat-cell i.on { background: var(--green); }
  .constellation-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(105px, 1fr)); gap: 8px; margin: 8px 0 14px; }
  .constellation-chip { border: 1px solid var(--border); border-radius: 5px; padding: 7px; color: var(--dim); font-size: 11px; }
  .constellation-chip strong { display: block; color: var(--green); font-size: 15px; margin-top: 3px; }
  @media (max-width: 600px) { .satellite-graphics { grid-template-columns: 1fr; } }
  footer {
    margin-top: 40px;
    text-align: center;
    color: var(--dim);
    font-size: 11px;
  }
  #clock { color: var(--amber); }
  #update-terminal-screen {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 10000;
    background: #050807;
    color: var(--green);
    padding: 22px;
    font-family: 'JetBrains Mono', monospace;
  }
  #update-terminal-screen.active { display: flex; flex-direction: column; }
  .terminal-heading {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    border-bottom: 1px solid #28523f;
    padding-bottom: 12px;
    color: var(--green);
    font-weight: 600;
  }
  #update-terminal-status { color: var(--amber); font-weight: 400; text-align: right; }
  #update-terminal-output {
    flex: 1;
    min-height: 0;
    overflow: auto;
    margin-top: 14px;
    padding: 12px;
    border: 1px solid #1e3b2d;
    background: #080c0a;
    color: #c8e6d5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font: 12px/1.55 'JetBrains Mono', monospace;
  }
  @media (max-width: 600px) {
    #update-terminal-screen { padding: 12px; }
    .terminal-heading { flex-direction: column; gap: 4px; }
    #update-terminal-status { text-align: left; }
  }
  .file-dialog-backdrop[hidden] { display: none; }
  .file-dialog-backdrop {
    position: fixed;
    inset: 0;
    z-index: 9000;
    display: grid;
    place-items: center;
    padding: 20px;
    background: rgba(0, 0, 0, 0.82);
  }
  .file-dialog {
    display: flex;
    flex-direction: column;
    width: min(720px, 100%);
    max-height: min(86vh, 900px);
    background: var(--card);
    border: 1px solid #28523f;
    border-radius: 10px;
    box-shadow: 0 18px 70px #000;
    padding: 18px;
  }
  .file-dialog-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  .file-dialog-heading h2 { color: var(--green); font-size: 1rem; letter-spacing: 1px; }
  .file-dialog-close {
    border: 1px solid var(--border);
    border-radius: 5px;
    background: #111;
    color: var(--text);
    font: inherit;
    font-size: 1.2rem;
    line-height: 1;
    padding: 5px 9px;
    cursor: pointer;
  }
  .file-dialog-intro { color: var(--dim); margin: 4px 0 12px; font-size: 11px; }
  #file-download-list { min-height: 0; overflow: auto; padding-right: 4px; }
  .file-category { color: var(--amber); font-size: 11px; letter-spacing: 1px; margin: 12px 0 6px; text-transform: uppercase; }
  .file-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    border-top: 1px solid var(--border);
    padding: 10px 2px;
  }
  .file-item-name { color: var(--text); font-weight: 600; }
  .file-item-description { color: var(--dim); font-size: 11px; }
  .file-download-button {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 1px solid #28523f;
    border-radius: 5px;
    background: #111;
    color: var(--green);
    font: inherit;
    cursor: pointer;
    padding: 6px 9px;
  }
  .file-download-button:hover { background: #002211; border-color: var(--green); }
  .file-download-button:disabled { cursor: wait; opacity: 0.55; }
  .file-download-button img { width: 16px; height: 16px; }
  #file-dialog-message { color: var(--amber); font-size: 11px; min-height: 1.5em; margin-top: 8px; }
  @media (max-width: 600px) {
    .file-dialog-backdrop { padding: 10px; }
    .file-dialog { max-height: 92vh; padding: 14px; }
    .file-item { align-items: flex-start; }
    .file-download-button span { display: none; }
  }
  .repo-panel-controls { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
  #repo-file-status { color: var(--dim); font-size: 11px; }
  .repo-refresh-button {
    flex: 0 0 auto;
    border: 1px solid #28523f;
    border-radius: 5px;
    background: #111;
    color: var(--green);
    font: inherit;
    font-size: 11px;
    cursor: pointer;
    padding: 4px 8px;
  }
  .repo-refresh-button:disabled { cursor: wait; opacity: 0.55; }
  .repo-tree {
    min-height: 130px;
    max-height: 360px;
    overflow: auto;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: #080c0a;
    color: #c8e6d5;
    font-size: 11px;
    line-height: 1.45;
    white-space: pre;
    word-break: normal;
  }
  .repo-associations { display: grid; gap: 4px; max-height: 190px; overflow: auto; }
  .repo-association { color: var(--dim); font-size: 10px; overflow-wrap: anywhere; }
  .repo-association strong { color: var(--green); font-weight: 400; }
</style>
</head>
<body>
  <header>
    <h1>RTK-BASE // DIAGNOSTICS</h1>
    <div class="header-actions">
      <div class="header-action-buttons">
        <button id="files-button" class="dashboard-action update-button" type="button" onclick="openFileDialog()">
          <img src="{{ url_for('static', filename='files-config.svg') }}" alt="" aria-hidden="true">
          <span>Files</span>
        </button>
        <button id="update-button" class="dashboard-action update-button" type="button" onclick="updatePi()">
          <img src="{{ url_for('static', filename='update.svg') }}" alt="" aria-hidden="true">
          <span>Update</span>
        </button>
        <button id="reboot-button" class="dashboard-action reboot-button" type="button" onclick="rebootPi()">
          <img src="{{ url_for('static', filename='reboot.svg') }}" alt="" aria-hidden="true">
          <span>Reboot Pi</span>
        </button>
      </div>
      <div id="action-message" role="status" aria-live="polite"></div>
    </div>
    <div class="subtitle">Live monitor · <span id="clock">–</span> · auto-refresh every 4 s</div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>System</h2>
      <div class="metric"><span>Dashboard version</span><span id="version">—</span></div>
      <div class="metric"><span>Hostname</span><span id="hostname">–</span></div>
      <div class="metric"><span>Uptime</span><span id="uptime">–</span></div>
      <div class="metric"><span>Temperature</span><span id="temp">–</span></div>
      <div class="metric"><span>Primary IP</span><span id="ip">–</span></div>
      <div class="metric"><span>Dashboard</span><span>HTTP :80</span></div>
    </div>

    <div class="card">
      <h2>Resources</h2>
      <div class="metric"><span>CPU</span><span id="cpu">–</span></div>
      <div class="bar"><div class="bar-fill" id="cpu-bar" style="width:0%"></div></div>
      <div class="metric"><span>Memory</span><span id="mem">–</span></div>
      <div class="bar"><div class="bar-fill" id="mem-bar" style="width:0%"></div></div>
      <div class="metric"><span>Disk</span><span id="disk">–</span></div>
      <div class="bar"><div class="bar-fill" id="disk-bar" style="width:0%"></div></div>
      <div class="metric"><span>Load (1 / 5 / 15)</span><span id="load">–</span></div>
    </div>

    <div class="card">
      <h2>RTK Stream Health</h2>
      <div class="metric"><span>Service</span><span id="str-status" class="status">–</span></div>
      <div class="metric"><span>RTCM output</span><span id="rtcm-port">TCP :2101</span></div>
      <div class="metric"><span>Connected clients</span><span id="rtcm-clients">—</span></div>
      <div class="metric"><span>Running for</span><span id="stream-uptime">—</span></div>
      <div class="metric"><span>Service restarts</span><span id="str-restarts">—</span></div>
      <div class="map-note">Client count is based on established TCP connections to the RTCM output port.</div>
      <pre id="str-log" class="scroll-fill" style="margin-top:12px; color:#aaa;"></pre>
    </div>

    <div class="card">
      <h2>GNSS / GPS</h2>
      <div class="metric"><span>Active mode</span><span id="active-mode">—</span></div>
      <div class="mode-controls">
        <button id="corrections-mode" onclick="setMode('corrections')">RTCM corrections</button>
        <button id="telemetry-mode" onclick="setMode('telemetry')">GPS telemetry</button>
      </div>
      <div id="mode-message" class="mode-message" role="status"></div>
      <div class="metric"><span>Telemetry</span><span id="gps-source">—</span></div>
      <div class="metric"><span>Fix</span><span id="gps-fix">—</span></div>
      <div class="metric"><span>Position</span><span id="gps-position">—</span></div>
      <div class="metric"><span>Altitude</span><span id="gps-altitude">—</span></div>
      <div class="metric"><span>Speed</span><span id="gps-speed">—</span></div>
      <div class="metric"><span>Satellites</span><span id="gps-satellites">—</span></div>
      <div class="metric"><span>Estimated accuracy</span><span id="gps-accuracy">—</span></div>
      <div class="metric"><span>HDOP / PDOP</span><span id="gps-dop">—</span></div>
      <div class="metric"><span>Fix time (UTC)</span><span id="gps-fix-time">—</span></div>
      <pre id="gps-satellite-detail" class="scroll-fill" style="margin-top:12px; color:#aaa;"></pre>
      <div id="satellite-status" class="map-note">Waiting for GPSD sky view</div>
    </div>

    <div class="card">
      <h2>Receiver Location</h2>
      <div id="gps-map" aria-label="Map showing receiver GPS position"></div>
      <div id="map-note" class="map-note">Waiting for GPS position…</div>
    </div>

    <div class="card">
      <h2>GNSS Constellations</h2>
      <div id="constellation-list" class="constellation-list"><span class="map-note">Waiting for satellite data…</span></div>
      <div class="map-note">Visible satellites and satellites used in the fix, grouped by constellation.</div>
    </div>

    <div class="card">
      <h2>Satellite View & Signal</h2>
      <div class="satellite-graphics">
        <svg id="satellite-sky" viewBox="0 0 240 240" role="img" aria-label="Satellite sky plot">
          <circle class="sky-ring" cx="120" cy="120" r="100" />
          <circle class="sky-ring" cx="120" cy="120" r="66" />
          <circle class="sky-ring" cx="120" cy="120" r="33" />
          <path class="sky-cross" d="M20 120h200M120 20v200" />
          <text class="sky-cardinal" x="120" y="12">N</text>
          <text class="sky-cardinal" x="228" y="123">E</text>
          <text class="sky-cardinal" x="120" y="238">S</text>
          <text class="sky-cardinal" x="12" y="123">W</text>
          <g id="sky-satellites"></g>
        </svg>
        <div id="signal-list" class="signal-list"><span class="map-note">Waiting for satellite data…</span></div>
      </div>
      <div class="map-note">Green satellites are being used in the fix. Sky plot shows azimuth and elevation.</div>
    </div>

    <div class="card">
      <h2>Network</h2>
      <div class="metric"><span>Wi-Fi interface</span><span id="wifi-interface">—</span></div>
      <div class="metric"><span>Network</span><span id="wifi-ssid">—</span></div>
      <div class="wifi-signal-display"><svg class="wifi-icon" viewBox="0 0 36 30" role="img" aria-label="Wi-Fi signal strength"><path class="wifi-segment" d="M2 9 Q18 -3 34 9"/><path class="wifi-segment" d="M7 15 Q18 7 29 15"/><path class="wifi-segment" d="M12 21 Q18 16 24 21"/><circle class="wifi-segment" cx="18" cy="27" r="1.8"/></svg><span id="wifi-signal">—</span></div>
      <div class="metric"><span>Wi-Fi link</span><span id="wifi-link">—</span></div>
      <div class="metric"><span>Frequency</span><span id="wifi-frequency">—</span></div>
      <div class="metric"><span>TX rate</span><span id="wifi-bitrate">—</span></div>
      <div class="metric"><span>RX / TX since boot</span><span id="net-traffic">—</span></div>
      <div class="scroll-stack">
        <pre id="network" class="scroll-fill"></pre>
        <pre id="ports" class="scroll-fill" style="color:#aaa;"></pre>
      </div>
    </div>

    <div class="card">
      <h2>USB Devices</h2>
      <pre id="usb" class="scroll-fill"></pre>
    </div>

    <div class="card">
      <h2>Serial Devices</h2>
      <pre id="serial" class="scroll-fill"></pre>
    </div>

    <div class="card">
      <h2>Repository File Tree</h2>
      <div class="repo-panel-controls">
        <span id="repo-file-status" role="status">Loading tracked files...</span>
        <button id="repo-refresh-button" class="repo-refresh-button" type="button" onclick="loadRepoFiles()">Refresh</button>
      </div>
      <pre id="repo-tree" class="repo-tree scroll-fill">Loading...</pre>
      <h3 class="file-category">Installed / Generated Files</h3>
      <div id="repo-associations" class="repo-associations scroll-fill"></div>
    </div>
  </div>

  <footer>
    RTK-Base Dashboard v{{ version }} · Raspberry Pi · data refreshes automatically
  </footer>

  <section id="update-terminal-screen" role="dialog" aria-modal="true" aria-labelledby="update-terminal-title">
    <div class="terminal-heading">
      <span id="update-terminal-title">RTK-BASE // SYSTEM UPDATE</span>
      <span id="update-terminal-status" role="status" aria-live="polite">Connecting to updater...</span>
    </div>
    <pre id="update-terminal-output" aria-label="Live output from the update and setup scripts"></pre>
  </section>

  <div id="file-dialog-backdrop" class="file-dialog-backdrop" hidden onclick="handleFileDialogBackdrop(event)">
    <section class="file-dialog" role="dialog" aria-modal="true" aria-labelledby="file-dialog-title">
      <div class="file-dialog-heading">
        <h2 id="file-dialog-title">Logs & Configuration</h2>
        <button class="file-dialog-close" type="button" aria-label="Close file downloads" onclick="closeFileDialog()">×</button>
      </div>
      <p class="file-dialog-intro">Choose a file to download from this Pi.</p>
      <div id="file-download-list" aria-live="polite">Loading available files...</div>
      <div id="file-dialog-message" role="status" aria-live="polite"></div>
    </section>
  </div>

<script>
let gpsMap = null;
let gpsMarker = null;
let mapHasFix = false;
const DOWNLOAD_ICON_URL = "{{ url_for('static', filename='download.svg') }}";
let updateOutputOffset = 0;
let updatePollTimer = null;
let updateReturnTimer = null;

function setPanelCollapsed(header, collapsed) {
  const panel = header.closest('.card');
  panel.classList.toggle('collapsed', collapsed);
  header.setAttribute('aria-expanded', String(!collapsed));
  try {
    localStorage.setItem(`rtk-panel:${header.textContent.trim()}`, collapsed ? 'closed' : 'open');
  } catch (error) { /* Storage can be unavailable in private browsing modes. */ }
  if (!collapsed && panel.querySelector('#gps-map') && gpsMap) {
    window.setTimeout(() => gpsMap.invalidateSize(), 50);
  }
}

function setupCollapsiblePanels() {
  document.querySelectorAll('.card > h2').forEach(header => {
    header.setAttribute('role', 'button');
    header.setAttribute('tabindex', '0');
    const key = `rtk-panel:${header.textContent.trim()}`;
    try {
      if (localStorage.getItem(key) === 'closed') {
        header.closest('.card').classList.add('collapsed');
        header.setAttribute('aria-expanded', 'false');
      } else {
        header.setAttribute('aria-expanded', 'true');
      }
    } catch (error) {
      header.setAttribute('aria-expanded', 'true');
    }
    header.addEventListener('click', () => {
      setPanelCollapsed(header, header.getAttribute('aria-expanded') === 'true');
    });
    header.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        header.click();
      }
    });
  });
}

function initializeMap() {
  const note = document.getElementById('map-note');
  if (typeof L === 'undefined') {
    note.textContent = 'Map library unavailable. The map requires an internet connection.';
    return;
  }
  gpsMap = L.map('gps-map', { scrollWheelZoom: false }).setView([0, 0], 2);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(gpsMap);
  window.setTimeout(() => gpsMap.invalidateSize(), 100);
}

function updateGpsMap(gps) {
  const note = document.getElementById('map-note');
  if (!gpsMap) initializeMap();
  if (!gpsMap) return;
  const lat = gps.latitude;
  const lon = gps.longitude;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    note.textContent = 'Waiting for a valid GPS fix.';
    return;
  }
  const position = L.latLng(lat, lon);
  if (!gpsMarker) {
    gpsMarker = L.circleMarker(position, {
      radius: 8, color: '#00ff9f', weight: 2, fillColor: '#00ff9f', fillOpacity: 0.7
    }).addTo(gpsMap).bindTooltip('RTK-Base receiver');
  } else {
    gpsMarker.setLatLng(position);
  }
  if (!mapHasFix) {
    gpsMap.setView(position, 15);
    mapHasFix = true;
  } else if (!gpsMap.getBounds().contains(position)) {
    gpsMap.panTo(position, { animate: false });
  }
  note.textContent = `Receiver position: ${lat.toFixed(6)}, ${lon.toFixed(6)}`;
}

function updateSatelliteGraphics(satellites) {
  const svgNamespace = 'http://www.w3.org/2000/svg';
  const plot = document.getElementById('sky-satellites');
  const list = document.getElementById('signal-list');
  const constellationList = document.getElementById('constellation-list');
  while (plot.firstChild) plot.removeChild(plot.firstChild);
  list.replaceChildren();
  constellationList.replaceChildren();
  if (!satellites || satellites.length === 0) {
    list.textContent = 'No satellite data available';
    constellationList.textContent = 'No constellation data available';
    return;
  }
  const constellations = new Map();
  satellites.forEach(sat => {
    const name = String(sat.id || 'Unknown').replace(/\s+\S+$/, '');
    const entry = constellations.get(name) || { visible: 0, used: 0 };
    entry.visible += 1;
    if (sat.used) entry.used += 1;
    constellations.set(name, entry);
  });
  [...constellations.entries()].sort((a, b) => a[0].localeCompare(b[0])).forEach(([name, counts]) => {
    const chip = document.createElement('div');
    chip.className = 'constellation-chip';
    chip.textContent = `${name} · ${counts.visible} visible`;
    const used = document.createElement('strong');
    used.textContent = `${counts.used} used`;
    chip.appendChild(used);
    constellationList.appendChild(chip);
  });
  satellites.forEach(satellite => {
    const az = Number(satellite.azimuth);
    const el = Number(satellite.elevation);
    const hasSkyPosition = satellite.azimuth !== null && satellite.elevation !== null &&
      Number.isFinite(az) && Number.isFinite(el) && el >= 0 && el <= 90;
    if (hasSkyPosition) {
      const angle = az * Math.PI / 180;
      const radius = 100 * (90 - el) / 90;
      const x = 120 + radius * Math.sin(angle);
      const y = 120 - radius * Math.cos(angle);
      const group = document.createElementNS(svgNamespace, 'g');
      const dot = document.createElementNS(svgNamespace, 'circle');
      dot.setAttribute('cx', x.toFixed(1));
      dot.setAttribute('cy', y.toFixed(1));
      dot.setAttribute('r', '5');
      dot.setAttribute('class', satellite.used ? 'sky-sat used' : 'sky-sat');
      const title = document.createElementNS(svgNamespace, 'title');
      title.textContent = `${satellite.id}: az ${az} deg, el ${el} deg${satellite.used ? ', used' : ''}`;
      dot.appendChild(title);
      group.appendChild(dot);
      const label = document.createElementNS(svgNamespace, 'text');
      label.setAttribute('x', x.toFixed(1));
      label.setAttribute('y', (y - 8).toFixed(1));
      label.setAttribute('class', 'sky-label');
      label.textContent = satellite.id;
      group.appendChild(label);
      plot.appendChild(group);
    }

    const signal = Number(satellite.signal);
    const hasSignal = satellite.signal !== null && Number.isFinite(signal);
    const row = document.createElement('div');
    row.className = 'signal-row';
    const label = document.createElement('span');
    label.textContent = `${satellite.used ? 'USED ' : ''}${satellite.id}`;
    const bars = document.createElement('div');
    bars.className = 'sat-cell';
    const strength = hasSignal ? Math.max(0, Math.min(4, Math.ceil(signal / 60 * 4))) : 0;
    for (let index = 1; index <= 4; index += 1) {
      const bar = document.createElement('i');
      if (index <= strength) bar.className = 'on';
      bars.appendChild(bar);
    }
    const value = document.createElement('span');
    value.textContent = hasSignal ? `${signal.toFixed(0)} dB-Hz` : '—';
    row.append(label, bars, value);
    list.appendChild(row);
  });
}

async function refresh() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();

    document.getElementById('clock').textContent = d.time;
    document.getElementById('version').textContent = d.version;
    document.getElementById('hostname').textContent = d.hostname;
    document.getElementById('uptime').textContent = d.uptime;
    document.getElementById('temp').textContent = d.temp;
    document.getElementById('ip').textContent = d.ip;

    document.getElementById('cpu').textContent = d.cpu + ' %';
    document.getElementById('cpu-bar').style.width = d.cpu + '%';
    document.getElementById('mem').textContent = d.mem;
    document.getElementById('mem-bar').style.width = d.mem_pct + '%';
    document.getElementById('disk').textContent = d.disk;
    document.getElementById('disk-bar').style.width = d.disk_pct + '%';
    document.getElementById('load').textContent = d.load;
    document.getElementById('rtcm-port').textContent = `TCP :${d.rtcm_port}`;
    document.getElementById('rtcm-clients').textContent = d.rtcm_clients;
    document.getElementById('str-restarts').textContent = d.str_restarts;
    document.getElementById('stream-uptime').textContent = d.stream_uptime;
    document.getElementById('wifi-interface').textContent = d.wifi.interface;
    document.getElementById('wifi-ssid').textContent = d.wifi.ssid;
    document.getElementById('wifi-signal').textContent = d.wifi.signal;
    const wifiStrength = Number(d.wifi.quality) || 0;
    document.querySelectorAll('.wifi-segment').forEach((segment, index) => {
      segment.classList.toggle('active', wifiStrength > (3 - index) * 25);
    });
    document.getElementById('wifi-link').textContent = d.wifi.link;
    document.getElementById('wifi-frequency').textContent = d.wifi.frequency || '—';
    document.getElementById('wifi-bitrate').textContent = d.wifi.bitrate || '—';
    document.getElementById('net-traffic').textContent = `${d.network_traffic.received} / ${d.network_traffic.sent} (${d.network_traffic.interface})`;

    const st = document.getElementById('str-status');
    st.textContent = d.str_status.toUpperCase();
    st.className = 'status ' + (d.str_status === 'active' ? 'ok' : 'fail');
    document.getElementById('str-log').textContent = d.str_log || 'No recent logs';

    document.getElementById('network').textContent = d.network || '–';
    document.getElementById('ports').textContent = d.ports || 'No RTK ports listening';
    document.getElementById('usb').textContent = d.usb;
    document.getElementById('serial').textContent = d.serial;
    document.getElementById('gps-source').textContent = d.gps.source;
    document.getElementById('gps-fix').textContent = d.gps.fix;
    document.getElementById('gps-position').textContent = d.gps.position;
    document.getElementById('gps-altitude').textContent = d.gps.altitude;
    document.getElementById('gps-speed').textContent = d.gps.speed;
    document.getElementById('gps-satellites').textContent = d.gps.satellites;
    document.getElementById('gps-accuracy').textContent = d.gps.accuracy;
    document.getElementById('gps-dop').textContent = `${d.gps.hdop} / ${d.gps.pdop}`;
    document.getElementById('gps-fix-time').textContent = d.gps.fix_time;
    document.getElementById('gps-satellite-detail').textContent = d.gps.satellite_detail || 'No satellite details';
    document.getElementById('satellite-status').textContent = d.gps.satellite_status;
    updateGpsMap(d.gps);
    updateSatelliteGraphics(d.gps.satellite_data);
    document.getElementById('active-mode').textContent = d.mode === 'telemetry' ? 'GPS telemetry' : d.mode === 'corrections' ? 'RTCM corrections' : 'Stopped';
    document.getElementById('corrections-mode').classList.toggle('active', d.mode === 'corrections');
    document.getElementById('telemetry-mode').classList.toggle('active', d.mode === 'telemetry');
    const updateStatus = d.update_status || 'Ready to update.';
    document.getElementById('action-message').textContent = updateStatus;
    document.getElementById('update-button').disabled = updateStatus.startsWith('Starting RTK-Base update') || updateStatus.startsWith('Updating RTK-Base');
  } catch (e) {
    console.error(e);
  }
}
async function setMode(mode) {
  const buttons = document.querySelectorAll('.mode-controls button');
  buttons.forEach(button => button.disabled = true);
  const message = document.getElementById('mode-message');
  message.textContent = 'Switching mode…';
  try {
    const response = await fetch('/api/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Mode switch failed');
    message.textContent = mode === 'telemetry'
      ? 'GPS telemetry active. RTCM corrections are paused.'
      : 'RTCM corrections active. GPS telemetry is paused.';
    await refresh();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
}
async function rebootPi() {
  if (!window.confirm('Reboot the Raspberry Pi now? The dashboard and RTCM stream will be unavailable briefly.')) return;
  const button = document.getElementById('reboot-button');
  const message = document.getElementById('action-message');
  button.disabled = true;
  message.textContent = 'Sending reboot command...';
  try {
    const response = await fetch('/api/reboot', { method: 'POST' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Reboot failed');
    message.textContent = 'Rebooting Pi...';
  } catch (error) {
    message.textContent = error.message;
    button.disabled = false;
  }
}
async function updatePi() {
  if (!window.confirm('Update RTK-Base now? This discards tracked local changes, pulls the latest repository version, and reruns setup.')) return;
  const button = document.getElementById('update-button');
  button.disabled = true;
  updateOutputOffset = 0;
  document.getElementById('update-terminal-output').textContent = '';
  document.getElementById('update-terminal-status').textContent = 'Starting update...';
  document.getElementById('update-terminal-screen').classList.add('active');
  if (updatePollTimer) window.clearTimeout(updatePollTimer);
  if (updateReturnTimer) window.clearTimeout(updateReturnTimer);
  try {
    const response = await fetch('/api/update', { method: 'POST' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Update failed to start');
    document.getElementById('update-terminal-status').textContent = 'Running update script...';
    pollUpdateOutput();
  } catch (error) {
    document.getElementById('update-terminal-output').textContent = `${error.message}\n`;
    document.getElementById('update-terminal-status').textContent = 'Could not start update.';
    updateReturnTimer = window.setTimeout(closeUpdateTerminal, 2500);
  }
}
async function openFileDialog() {
  const backdrop = document.getElementById('file-dialog-backdrop');
  const list = document.getElementById('file-download-list');
  const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
  const bodyPaddingRight = parseFloat(getComputedStyle(document.body).paddingRight) || 0;
  document.body.style.paddingRight = `${bodyPaddingRight + scrollbarWidth}px`;
  backdrop.hidden = false;
  document.body.style.overflow = 'hidden';
  document.getElementById('file-dialog-message').textContent = '';
  list.textContent = 'Loading available files...';
  document.querySelector('.file-dialog-close').focus();
  try {
    const response = await fetch('/api/downloads');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not list files');
    renderDownloadItems(result.files);
  } catch (error) {
    list.textContent = error.message;
  }
}
async function loadRepoFiles() {
  const button = document.getElementById('repo-refresh-button');
  const status = document.getElementById('repo-file-status');
  button.disabled = true;
  status.textContent = 'Reading repository tree...';
  try {
    const response = await fetch('/api/repo-files', { cache: 'no-store' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not read repository files');
    document.getElementById('repo-tree').textContent = result.tree || '(Repository is empty)';
    const associations = document.getElementById('repo-associations');
    associations.replaceChildren();
    result.associations.forEach(item => {
      const row = document.createElement('div');
      row.className = 'repo-association';
      const source = document.createElement('strong');
      source.textContent = item.source;
      const state = item.generated ? 'generated' : item.installed ? 'installed' : 'not installed';
      row.append(source, document.createTextNode(` → ${item.target} (${state})`));
      associations.appendChild(row);
    });
    status.textContent = `${result.file_count} tracked files · ${result.root}`;
  } catch (error) {
    document.getElementById('repo-tree').textContent = 'Repository tree is unavailable.';
    document.getElementById('repo-associations').replaceChildren();
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
function closeFileDialog() {
  document.getElementById('file-dialog-backdrop').hidden = true;
  document.body.style.overflow = '';
  document.body.style.paddingRight = '';
  document.getElementById('files-button').focus();
}
function handleFileDialogBackdrop(event) {
  if (event.target.id === 'file-dialog-backdrop') closeFileDialog();
}
function renderDownloadItems(items) {
  const list = document.getElementById('file-download-list');
  list.replaceChildren();
  const categories = new Map();
  items.forEach(item => {
    if (!categories.has(item.category)) categories.set(item.category, []);
    categories.get(item.category).push(item);
  });
  categories.forEach((categoryItems, category) => {
    const heading = document.createElement('h3');
    heading.className = 'file-category';
    heading.textContent = category;
    list.appendChild(heading);
    categoryItems.forEach(item => {
      const row = document.createElement('div');
      row.className = 'file-item';
      const details = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'file-item-name';
      name.textContent = item.name;
      const description = document.createElement('div');
      description.className = 'file-item-description';
      description.textContent = `${item.description} · ${item.filename}`;
      details.append(name, description);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'file-download-button';
      button.setAttribute('aria-label', `Download ${item.name}`);
      const icon = document.createElement('img');
      icon.src = DOWNLOAD_ICON_URL;
      icon.alt = '';
      icon.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span');
      label.textContent = 'Download';
      button.append(icon, label);
      button.addEventListener('click', () => downloadFile(item, button));
      row.append(details, button);
      list.appendChild(row);
    });
  });
}
async function downloadFile(item, button) {
  const message = document.getElementById('file-dialog-message');
  message.textContent = `Preparing ${item.filename}...`;
  button.disabled = true;
  try {
    const response = await fetch(`/api/downloads/${encodeURIComponent(item.id)}`);
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || `Could not download ${item.filename}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = item.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.textContent = `Downloaded ${item.filename}.`;
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !document.getElementById('file-dialog-backdrop').hidden) closeFileDialog();
});
function closeUpdateTerminal() {
  document.getElementById('update-terminal-screen').classList.remove('active');
  document.getElementById('update-button').disabled = false;
  if (updatePollTimer) window.clearTimeout(updatePollTimer);
  updatePollTimer = null;
}
async function pollUpdateOutput() {
  try {
    const response = await fetch(`/api/update/output?offset=${updateOutputOffset}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Update output endpoint unavailable');
    const result = await response.json();
    if (result.output) {
      const output = document.getElementById('update-terminal-output');
      output.textContent += result.output;
      output.scrollTop = output.scrollHeight;
    }
    updateOutputOffset = result.offset;
    document.getElementById('update-terminal-status').textContent = result.status;
    if (result.done) {
      updateReturnTimer = window.setTimeout(() => {
        closeUpdateTerminal();
        if (result.success) window.location.reload();
      }, 2200);
      return;
    }
  } catch (error) {
    document.getElementById('update-terminal-status').textContent = 'Dashboard restarting or reconnecting...';
  }
  updatePollTimer = window.setTimeout(pollUpdateOutput, 800);
}
setupCollapsiblePanels();
refresh();
loadRepoFiles();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML, version=APP_VERSION)

@app.route("/api/data")
def api_data():
    cpu = psutil.cpu_percent(interval=0.25)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg()
    str_status, str_log = get_str2str()

    ip = "N/A"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    return jsonify({
        "version": APP_VERSION,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "uptime": get_uptime(),
        "temp": get_temp(),
        "ip": ip,
        "cpu": round(cpu, 1),
        "mem": f"{mem.used // 1024 // 1024} / {mem.total // 1024 // 1024} MB ({mem.percent}%)",
        "mem_pct": mem.percent,
        "disk": f"{disk.used // 1024 // 1024 // 1024:.1f} / {disk.total // 1024 // 1024 // 1024:.1f} GB ({disk.percent}%)",
        "disk_pct": disk.percent,
        "load": f"{load[0]:.2f}   {load[1]:.2f}   {load[2]:.2f}",
        "rtcm_port": get_rtcm_port(),
        "rtcm_clients": get_rtcm_client_count(),
        "str_restarts": get_service_restarts(),
        "stream_uptime": get_stream_uptime(),
        "wifi": get_wifi_data(),
        "network_traffic": get_network_traffic(),
        "str_status": str_status,
        "str_log": str_log,
        "network": get_network(),
        "ports": get_listening(),
        "usb": get_usb(),
        "serial": get_serial(),
        "gps": get_gps_data(),
        "mode": get_mode(),
        "update_status": get_update_status(),
    })

@app.route("/api/mode", methods=["POST"])
def api_mode():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode")
    if mode not in ("corrections", "telemetry"):
        return jsonify({"error": "Mode must be corrections or telemetry"}), 400
    try:
        result = subprocess.run(
            ["sudo", "/usr/local/sbin/rtk-base-set-mode", mode],
            capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return jsonify({"error": "Could not run the mode switch command"}), 500
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or "Mode switch failed"}), 500
    return jsonify({"mode": get_mode()})

@app.route("/api/reboot", methods=["POST"])
def api_reboot():
    try:
        result = subprocess.run(
            ["sudo", "/usr/bin/systemctl", "reboot"],
            capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return jsonify({"error": "Could not run the reboot command"}), 500
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or "Reboot command failed"}), 500
    return jsonify({"status": "rebooting"}), 202

@app.route("/api/update", methods=["POST"])
def api_update():
    if get_update_status().startswith(("Starting RTK-Base update", "Updating RTK-Base")):
        return jsonify({"error": "An RTK-Base update is already running"}), 409
    log_path = Path("/var/log/rtk-base-update.log")
    try:
        previous_log_stat = log_path.stat()
        previous_log_signature = (previous_log_stat.st_mtime_ns, previous_log_stat.st_size)
    except OSError:
        previous_log_signature = None
    try:
        subprocess.Popen(
            ["sudo", "-n", "/usr/local/sbin/rtk-base-update"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return jsonify({"error": "Could not start the update command"}), 500
    for _ in range(60):
        if get_update_status().startswith(("Starting RTK-Base update", "Updating RTK-Base")):
            return jsonify({"status": "updating"}), 202
        try:
            log_stat = log_path.stat()
            log_signature = (log_stat.st_mtime_ns, log_stat.st_size)
        except OSError:
            log_signature = None
        if log_signature is not None and log_signature != previous_log_signature and log_stat.st_size > 0:
            return jsonify({"status": "updating"}), 202
        time.sleep(0.05)
    return jsonify({"error": "Updater did not start. Check /var/log/rtk-base-update.log."}), 500

@app.route("/api/update/output")
def api_update_output():
    try:
        offset = max(0, int(request.args.get("offset", "0")))
    except ValueError:
        return jsonify({"error": "Invalid output offset"}), 400

    output = b""
    try:
        with open("/var/log/rtk-base-update.log", "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            offset = min(offset, size)
            log_file.seek(offset)
            output = log_file.read(65536)
    except OSError:
        pass

    status = get_update_status()
    success = status in ("Update complete.", "Update complete. Dashboard restarted.")
    done = success or status.startswith("Update failed")
    return jsonify({
        "output": output.decode("utf-8", errors="replace"),
        "offset": offset + len(output),
        "status": status,
        "done": done,
        "success": success,
    })

@app.route("/api/downloads")
def api_downloads():
    return jsonify({"files": DOWNLOAD_ITEMS})

@app.route("/api/downloads/<file_id>")
def api_download_file(file_id: str):
    item = next((entry for entry in DOWNLOAD_ITEMS if entry["id"] == file_id), None)
    if item is None:
        return jsonify({"error": "Unknown download item"}), 404
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/rtk-base-download-file", file_id],
            capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return jsonify({"error": "Could not read the selected file"}), 500
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        return jsonify({"error": error or "The selected file is not available"}), 404
    response = Response(
        result.stdout,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{item["filename"]}"'},
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.route("/api/repo-files")
def api_repo_files():
    try:
        repo_path = Path("/etc/rtk-base-update-repo").read_text(encoding="utf-8").strip()
    except OSError:
        return jsonify({"error": "Repository path is not configured; run setup first"}), 503
    repo = Path(repo_path)
    if not repo.is_dir() or not (repo / ".git").exists():
        return jsonify({"error": "Configured RTK-Base repository is unavailable"}), 503
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={repo}", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return jsonify({"error": "Could not list tracked repository files"}), 500
    if result.returncode != 0:
        return jsonify({"error": "Could not list tracked repository files"}), 500

    paths = [path for path in result.stdout.decode("utf-8", errors="replace").split("\0") if path]
    association_map = {}
    associations = []
    for entry in REPO_ASSOCIATIONS:
        association_map.setdefault(entry["source"], []).append(entry["target"])
        associations.append({
            **entry,
            "generated": entry.get("kind") == "generated",
            "installed": Path(entry["target"]).exists(),
        })
    return jsonify({
        "root": repo.name,
        "file_count": len(paths),
        "tree": render_repo_tree(paths, association_map),
        "associations": associations,
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
