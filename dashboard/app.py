#!/usr/bin/env python3
"""
RTK-Base Live Diagnostics Dashboard
Terminal-style web interface
"""

from flask import Flask, render_template_string, jsonify
import subprocess, os, socket, psutil
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
    return run("ss -ltnp | grep -E ':2101|:8080' || true")

def get_usb() -> str:
    return run("lsusb") or "No USB devices found"

def get_serial() -> str:
    return run("ls -l /dev/serial/by-id/ 2>/dev/null") or "No serial devices"

def get_network() -> str:
    return run("ip -4 addr show | grep -E 'inet '")

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
  } catch (e) {
    console.error(e);
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
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
