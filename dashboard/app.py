#!/usr/bin/env python3
"""
RTK-Base Live Diagnostics Dashboard
Terminal-style web interface
"""

from flask import Flask, render_template_string, jsonify, request
import json, subprocess, os, socket, psutil
from datetime import datetime, timedelta

app = Flask(__name__)

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

def get_listening() -> str:
    return run("ss -ltnp | grep -E ':2101|:2948|:8080' || true")

def get_usb() -> str:
    return run("lsusb") or "No USB devices found"

def get_serial() -> str:
    return run("ls -l /dev/serial/by-id/ 2>/dev/null") or "No serial devices"

def get_network() -> str:
    try:
        routes = run("ip -4 route show default")
        default_iface = next((part.split()[4] for part in routes.splitlines()
                              if len(part.split()) >= 5 and part.split()[0] == "default"), None)
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
    }
    try:
        with socket.create_connection(("127.0.0.1", 2948), timeout=0.5) as conn:
            conn.settimeout(0.5)
            conn.sendall(b'?WATCH={"enable":true,"json":true};\n')
            stream = conn.makefile("r", encoding="utf-8", errors="replace")
            tpv = None
            sky = None
            for _ in range(30):
                line = stream.readline()
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
                if tpv and sky:
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
                satellites = (sky or {}).get("satellites", [])
                used = [sat for sat in satellites if sat.get("used")]
                result["satellites"] = f"{len(used)} used / {len(satellites)} visible"
                result["satellite_data"] = [
                    {
                        "id": f"{sat.get('gnssid', '')}-{sat.get('svid', sat.get('PRN', '?'))}",
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
                        f"{sat.get('gnssid', '')}{sat.get('svid', sat.get('PRN', '?'))}: "
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
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 18px;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px;
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
  }
  .card h2::before {
    content: "▶";
    color: var(--green);
    font-size: 0.65rem;
  }
  pre {
    white-space: pre-wrap;
    word-break: break-all;
    font-size: 12px;
    color: var(--text);
  }
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
  .satellite-graphics { display: grid; grid-template-columns: minmax(190px, 240px) 1fr; gap: 18px; align-items: center; }
  #satellite-sky { width: 100%; max-width: 240px; height: auto; }
  .sky-ring { fill: none; stroke: #28523f; stroke-width: 1; }
  .sky-cross { stroke: #1e3b2d; stroke-width: 1; }
  .sky-cardinal { fill: var(--dim); font: 10px 'JetBrains Mono', monospace; text-anchor: middle; }
  .sky-sat { fill: #666; stroke: #0a0a0a; stroke-width: 1.5; }
  .sky-sat.used { fill: var(--green); }
  .sky-label { fill: var(--text); font: 8px 'JetBrains Mono', monospace; text-anchor: middle; }
  .signal-list { display: grid; gap: 6px; max-height: 240px; overflow: auto; }
  .signal-row { display: grid; grid-template-columns: 52px 1fr 40px; gap: 8px; align-items: center; font-size: 11px; }
  .signal-track { height: 7px; background: #1a1a1a; border-radius: 5px; overflow: hidden; }
  .signal-fill { height: 100%; background: #777; border-radius: inherit; }
  .signal-fill.used { background: var(--green); }
  @media (max-width: 600px) { .satellite-graphics { grid-template-columns: 1fr; } }
  footer {
    margin-top: 40px;
    text-align: center;
    color: var(--dim);
    font-size: 11px;
  }
  #clock { color: var(--amber); }
</style>
</head>
<body>
  <header>
    <h1>RTK-BASE // DIAGNOSTICS</h1>
    <div class="subtitle">Live monitor · <span id="clock">–</span> · auto-refresh every 4 s</div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>System</h2>
      <div class="metric"><span>Hostname</span><span id="hostname">–</span></div>
      <div class="metric"><span>Uptime</span><span id="uptime">–</span></div>
      <div class="metric"><span>Temperature</span><span id="temp">–</span></div>
      <div class="metric"><span>Primary IP</span><span id="ip">–</span></div>
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
      <h2>str2str Service</h2>
      <div class="metric"><span>Status</span><span id="str-status" class="status">–</span></div>
      <pre id="str-log" style="margin-top:12px; max-height:180px; overflow:auto; color:#aaa;"></pre>
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
      <pre id="gps-satellite-detail" style="margin-top:12px; max-height:140px; overflow:auto; color:#aaa;"></pre>
    </div>

    <div class="card">
      <h2>Receiver Location</h2>
      <div id="gps-map" aria-label="Map showing receiver GPS position"></div>
      <div id="map-note" class="map-note">Waiting for GPS position…</div>
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
      <h2>Network & Ports</h2>
      <pre id="network"></pre>
      <pre id="ports" style="margin-top:12px; color:#aaa;"></pre>
    </div>

    <div class="card">
      <h2>USB Devices</h2>
      <pre id="usb"></pre>
    </div>

    <div class="card">
      <h2>Serial Devices</h2>
      <pre id="serial"></pre>
    </div>
  </div>

  <footer>
    RTK-Base Dashboard · Raspberry Pi · data refreshes automatically
  </footer>

<script>
let gpsMap = null;
let gpsMarker = null;
let mapHasFix = false;

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
  while (plot.firstChild) plot.removeChild(plot.firstChild);
  list.replaceChildren();
  if (!satellites || satellites.length === 0) {
    list.textContent = 'No satellite data available';
    return;
  }
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
    const track = document.createElement('div');
    track.className = 'signal-track';
    const fill = document.createElement('div');
    fill.className = satellite.used ? 'signal-fill used' : 'signal-fill';
    fill.style.width = `${hasSignal ? Math.max(0, Math.min(100, signal / 60 * 100)) : 0}%`;
    track.appendChild(fill);
    const value = document.createElement('span');
    value.textContent = hasSignal ? `${signal.toFixed(0)} dB-Hz` : '—';
    row.append(label, track, value);
    list.appendChild(row);
  });
}

async function refresh() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();

    document.getElementById('clock').textContent = d.time;
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
    document.getElementById('gps-satellite-detail').textContent = d.gps.satellite_detail || 'No satellite details';
    updateGpsMap(d.gps);
    updateSatelliteGraphics(d.gps.satellite_data);
    document.getElementById('active-mode').textContent = d.mode === 'telemetry' ? 'GPS telemetry' : d.mode === 'corrections' ? 'RTCM corrections' : 'Stopped';
    document.getElementById('corrections-mode').classList.toggle('active', d.mode === 'corrections');
    document.getElementById('telemetry-mode').classList.toggle('active', d.mode === 'telemetry');
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
refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

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
        "str_status": str_status,
        "str_log": str_log,
        "network": get_network(),
        "ports": get_listening(),
        "usb": get_usb(),
        "serial": get_serial(),
        "gps": get_gps_data(),
        "mode": get_mode(),
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
