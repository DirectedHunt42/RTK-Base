#!/usr/bin/env python3
"""
RTK-Base Live Diagnostics Dashboard
Terminal-style web interface
"""

from flask import Flask, render_template, jsonify, request, Response
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
              "dbm": None, "quality": 0, "link": "No wireless interface detected"}
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
                    result["dbm"] = dbm
                    result["quality"] = max(0, min(100, round((dbm + 100) * 2)))
                except ValueError:
                    pass
        elif line.startswith("freq:"):
            result["frequency"] = f"{line.split(':', 1)[1].strip()} MHz"
        elif line.startswith("tx bitrate:"):
            result["bitrate"] = line.split(":", 1)[1].strip()
    return result

def get_ethernet_data() -> list:
    """Return wired interfaces with an active physical carrier."""
    interfaces = []
    for name, addresses in psutil.net_if_addrs().items():
        if name == "lo" or os.path.isdir(f"/sys/class/net/{name}/wireless"):
            continue
        try:
            interface_type = Path(f"/sys/class/net/{name}/type")
            carrier_file = Path(f"/sys/class/net/{name}/carrier")
            if interface_type.read_text(encoding="ascii").strip() != "1":
                continue
            if carrier_file.read_text(encoding="ascii").strip() != "1":
                continue
        except (OSError, ValueError):
            continue
        ipv4 = [address.address for address in addresses
                if address.family == socket.AF_INET and not address.address.startswith("127.")]
        interfaces.append({"interface": name, "addresses": ipv4})
    return interfaces

_traffic_sample = None

def get_network_traffic() -> dict:
    """Return default-interface totals and rates since the previous dashboard poll."""
    global _traffic_sample
    iface = get_default_interface()
    counters = psutil.net_io_counters(pernic=True).get(iface) if iface else None
    now = time.monotonic()
    if not counters:
        _traffic_sample = None
        return {"interface": iface or "\u2014", "received": "\u2014", "sent": "\u2014", "rx_rate": 0, "tx_rate": 0}
    rx_rate = tx_rate = 0
    if _traffic_sample and _traffic_sample[0] == iface:
        elapsed = now - _traffic_sample[1]
        if elapsed > 0:
            rx_rate = max(0, (counters.bytes_recv - _traffic_sample[2]) / elapsed)
            tx_rate = max(0, (counters.bytes_sent - _traffic_sample[3]) / elapsed)
    _traffic_sample = (iface, now, counters.bytes_recv, counters.bytes_sent)
    return {
        "interface": iface,
        "received": f"{counters.bytes_recv / (1024 ** 2):.1f} MiB",
        "sent": f"{counters.bytes_sent / (1024 ** 2):.1f} MiB",
        "rx_rate": round(rx_rate),
        "tx_rate": round(tx_rate),
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
            conn.settimeout(0.25)
            conn.sendall(b'?WATCH={"enable":true,"json":true};?POLL;\n')
            tpv = None
            sky = None
            sky_report_received = False
            pending = b""
            # TPV and SKY are separate GPSD reports. Keep reading after POLL/TPV
            # so a fast position response cannot hide the satellite report.
            deadline = time.monotonic() + 1.25
            while time.monotonic() < deadline:
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                pending += chunk
                lines = pending.split(b"\n")
                pending = lines.pop()
                for raw_line in lines:
                    try:
                        message = json.loads(raw_line.decode("utf-8", errors="replace"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if message.get("class") == "TPV":
                        tpv = message
                    elif message.get("class") == "SKY":
                        sky = message
                        sky_report_received = True
                    elif message.get("class") == "POLL":
                        polled_tpv = message.get("tpv") or []
                        polled_sky = message.get("sky") or []
                        if polled_tpv:
                            tpv = polled_tpv[-1]
                        if polled_sky:
                            sky = polled_sky[-1]
                            sky_report_received = True
                if sky_report_received and (sky or {}).get("satellites"):
                    break
            if tpv or sky_report_received:
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
    if status.startswith(("Starting RTK-Base update", "Updating RTK-Base", "APT upgrade available:")):
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
    {"source": "scripts/receiver/set_mode.sh", "target": "/usr/local/sbin/rtk-base-set-mode"},
    {"source": "scripts/receiver/start_str2str.py", "target": "/usr/local/sbin/rtk-base-start-str2str"},
    {"source": "scripts/maintenance/update.sh", "target": "/usr/local/sbin/rtk-base-update"},
    {"source": "scripts/maintenance/download_file.sh", "target": "/usr/local/sbin/rtk-base-download-file"},
    {"source": "services/systemd/str2str.service", "target": "/etc/systemd/system/str2str.service"},
    {"source": "services/systemd/rtk-dashboard.service", "target": "/etc/systemd/system/rtk-dashboard.service"},
    {"source": "services/systemd/rtk-gpsd.service", "target": "/etc/systemd/system/rtk-gpsd.service"},
    {"source": "services/nginx/rtk-base.conf", "target": "/etc/nginx/sites-available/rtk-base"},
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


@app.route("/")
def index():
    return render_template("index.html", version=APP_VERSION)

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

    local_hostname = socket.gethostname()
    if not local_hostname.lower().endswith(".local"):
        local_hostname += ".local"

    rtcm_client_count = get_rtcm_client_count()

    return jsonify({
        "version": APP_VERSION,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "local_hostname": local_hostname,
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
        "rtcm_clients": rtcm_client_count,
        "str_restarts": get_service_restarts(),
        "stream_uptime": get_stream_uptime(),
        "wifi": get_wifi_data(),
        "ethernet": get_ethernet_data(),
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
    if get_update_status().startswith(("Starting RTK-Base update", "Updating RTK-Base", "APT upgrade available:")):
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
        if get_update_status().startswith(("Starting RTK-Base update", "Updating RTK-Base", "APT upgrade available:")):
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

@app.route("/api/update/apt-upgrade", methods=["POST"])
def api_update_apt_upgrade():
    if not get_update_status().startswith("APT upgrade available:"):
        return jsonify({"error": "There is no pending system upgrade prompt"}), 409
    payload = request.get_json(silent=True) or {}
    approve = payload.get("approve")
    if not isinstance(approve, bool):
        return jsonify({"error": "An approve choice is required"}), 400
    option = "--approve-apt-upgrade" if approve else "--decline-apt-upgrade"
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/rtk-base-update", option],
            capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return jsonify({"error": "Could not submit the system upgrade choice"}), 500
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip() or "System upgrade choice was rejected"}), 500
    return jsonify({"status": "upgrade" if approve else "skipped"}), 202

@app.route("/api/downloads")
def api_downloads():
    return jsonify({"files": DOWNLOAD_ITEMS})

@app.route("/api/readme")
def api_readme():
    try:
        repo_path = Path("/etc/rtk-base-update-repo").read_text(encoding="utf-8").strip()
        readme_path = Path(repo_path) / "README.md"
    except OSError:
        readme_path = Path(__file__).resolve().parent.parent / "README.md"
    try:
        content = readme_path.read_text(encoding="utf-8")
    except OSError:
        return jsonify({"error": "README file is unavailable on the configured repository"}), 404
    response = jsonify({"content": content})
    response.headers["Cache-Control"] = "no-store"
    return response

@app.route("/api/license")
def api_license():
    try:
        repo_path = Path("/etc/rtk-base-update-repo").read_text(encoding="utf-8").strip()
        license_path = Path(repo_path) / "LICENSE.txt"
    except OSError:
        license_path = Path(__file__).resolve().parent.parent / "LICENSE.txt"
    try:
        content = license_path.read_text(encoding="utf-8")
    except OSError:
        return jsonify({"error": "Licence file is unavailable on the configured repository"}), 404
    response = jsonify({"content": content})
    response.headers["Cache-Control"] = "no-store"
    return response

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
