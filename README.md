# RTK-Base

DIY RTK base station for a Raspberry Pi and u-blox GNSS receiver. The Pi reads
the receiver and serves RTCM corrections over TCP for clients such as Mission
Planner.

## Features

- Streams RTCM 3 over TCP, preferring port **2101** and finding a free nearby
  port when needed
- Starts the RTCM stream and diagnostics dashboard at boot
- Live system and network diagnostics, plus switchable GPS telemetry
- Wi-Fi link strength and network traffic counters
- Collapsible dashboard panels
- Dashboard available on the standard HTTP port
- Dashboard update control with a live terminal view for the updater and setup output
- Satellite sky view, signal strengths, and receiver position map in telemetry mode

Dashboard version: **0.3.1** (`dashboard/VERSION`)

## Hardware

- Raspberry Pi with Raspberry Pi OS
- u-blox GNSS receiver (such as F9P or M8P) connected by USB

## Install

```bash
git clone https://github.com/DirectedHunt42/RTK-Base.git
cd RTK-Base
chmod +x setup.sh
sudo ./setup.sh
```

After setup, open `http://<pi-ip>` in a browser. For example, if the Pi's
address is `192.168.0.41`, visit `http://192.168.0.41`.
Connect the GNSS receiver before running setup; the installer detects its
`/dev/serial/by-id` device and installs RTKLIB (`str2str`), GPSD, Flask, nginx,
and the system services automatically. If port 2101 is occupied, the stream
service tries ports 2102 through 2120 each time it starts.

Use the dashboard's **Update** button to pull the latest repository version
and rerun setup. Updating runs `git reset --hard` first, so tracked local
changes in the checkout are discarded. Update progress and errors appear in
the dashboard; detailed output is logged to `/var/log/rtk-base-update.log`.

Setup checks that it can find the receiver device and that RTKLIB's `str2str`
executable was installed. It enables and starts the services, then prints their
status and the selected port. These checks confirm the Pi software is present
and running; they do not confirm that the receiver is tracking satellites or
that its output contains valid corrections.

## Connections

| Service | Address | Purpose |
| --- | --- | --- |
| RTCM stream | `tcp://<pi-ip>:<rtcm-port>` | Correction data for Mission Planner |
| Dashboard | `http://<pi-ip>` (port 80) | Live diagnostics |

In Mission Planner, open **Setup → Optional Hardware → RTK/GPS Inject** and
select **TCP Client**. Enter the Pi's IP address and actual RTCM port. Port
2101 is preferred; if it is occupied, the service selects the first free port
from 2102 through 2120. The active port appears in the dashboard System panel
and in setup's completion message. Leave both NTRIP options unchecked.

## GPS and stream modes

The dashboard starts in **RTCM corrections** mode. Use the controls in the
GNSS / GPS card to switch between:

- **RTCM corrections**: `str2str` owns the receiver port and serves data on
  the selected RTCM TCP port.
- **GPS telemetry**: GPSD owns the receiver port and the dashboard displays
  fix type, position, altitude, speed, and satellites used/visible.

The receiver exposes one configured serial port, so these modes are exclusive.
RTCM corrections pause while GPS telemetry is selected. Switching back restarts
the RTCM stream. Setup installs RTKLIB's `str2str`, detects the connected
receiver, configures both services, and grants the
dashboard permission to switch only between these two modes. The system GPSD
socket service is disabled so it cannot claim the receiver port independently.
Anyone with access to the dashboard can change the active mode.

In corrections mode, `str2str` forwards the receiver's RTCM 3 stream unchanged
over TCP. Configure the receiver as an RTK base and make sure its serial/USB
connection outputs RTCM 3 messages, including observation messages and a valid
reference-position message such as RTCM 1005. Setup does not change receiver
settings; those are saved on the receiver itself. Mission Planner needs valid
base-position and observation messages to compute an RTK solution.

### Receiver readiness and first run

Before expecting an RTK solution, confirm all of the following:

1. The receiver is connected to a GNSS antenna with a clear view of the sky.
2. The receiver is configured as a stationary base and outputs RTCM 3 on its
   USB/serial connection. The stream should include observation messages such
   as GPS MSM and a valid base reference-position message such as RTCM 1005.
3. The base position has been surveyed or fixed in the receiver's own base
   configuration. Keep the antenna stationary during survey-in.

Receiver setup differs by model. The [CubePilot HERE 3 manual](https://github.com/CubePilot/cubepilot-docs/blob/master/here-3/here-3-manual.md)
describes its base-station survey and RTCM status workflow.

After setup, use these commands to check the Pi-side services and stream:

```bash
# Confirm services are active
sudo systemctl status str2str rtk-dashboard nginx

# Confirm which TCP port str2str selected
cat /var/lib/rtk-base/stream-port
sudo ss -ltnp

# Inspect receiver and stream status
sudo journalctl -u str2str -n 50 --no-pager
```

The dashboard's GPS telemetry mode can help confirm a position fix and visible
satellites, but selecting it stops `str2str` while GPSD uses the receiver. Switch
back to **RTCM corrections** before checking the correction stream in Mission
Planner. A running service and an open TCP port alone do not prove that valid
RTCM messages are reaching the client.

GPS telemetry mode also shows the receiver on an interactive OpenStreetMap
map, a satellite sky plot, signal-strength bars, DOP values, and GPSD's
estimated accuracy and fix time. The map and its tiles need an internet
connection; the GPS and satellite graphics use the receiver's GPSD data. The
GPSD sky view reports visible satellites and marks which ones are used in the
current fix.

The Resources panel shows Wi-Fi signal in dBm, a rough signal meter, link rate,
frequency, and total traffic on the default network interface since boot. The
System panel shows the RTCM output port, connected RTCM clients, and stream
restart count. Select any panel heading to collapse or expand it; that choice
is remembered in the browser.

## Useful commands

```bash
# Check service status
sudo systemctl status str2str
sudo systemctl status rtk-dashboard
sudo systemctl status nginx

# Follow service logs
sudo journalctl -u str2str -f
sudo journalctl -u rtk-dashboard -f

# Restart services
sudo systemctl restart str2str rtk-dashboard nginx
```

Made for reliable field use.
