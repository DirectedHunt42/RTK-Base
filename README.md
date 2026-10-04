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
- Satellite sky view, signal strengths, and receiver position map in telemetry mode

Dashboard version: **0.3.0** (`dashboard/VERSION`)

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

In corrections mode, `str2str` converts UBX raw observations to RTCM 3. The
receiver must provide UBX raw observation and navigation messages, and be
configured for stationary base operation. To include RTCM message 1005, set
the antenna's surveyed position (latitude, longitude, height in metres) in
`/etc/default/rtk-base` as `RTK_BASE_POSITION="<lat> <lon> <height>"`, then run
`sudo systemctl restart str2str`. Without a known position, the service omits
1005 instead of publishing an invalid zero coordinate; Mission Planner needs a
valid reference position before it can compute an RTK solution. Receiver
configuration differs by model and firmware, so setup does not change receiver
settings automatically.

### Receiver readiness and first run

Before expecting an RTK solution, confirm all of the following:

1. The receiver is connected to a GNSS antenna with a clear view of the sky.
2. The receiver is configured to output UBX raw observations and navigation
   data on its USB/serial connection. For u-blox devices, these are commonly
   UBX-RXM-RAWX and UBX-RXM-SFRBX messages; exact setup depends on receiver
   model and firmware.
3. The receiver is configured for stationary base use and has a valid base
   position. A surveyed fixed position gives the best absolute accuracy. A
   receiver's survey-in feature can establish an approximate position if
   configured and allowed to complete; keep the antenna stationary during
   survey-in.
4. The antenna position is set in `/etc/default/rtk-base` as described above
   so `str2str` can include RTCM 1005.

For a u-blox receiver, configure and save these settings with the appropriate
u-blox configuration tool for its generation. Setup intentionally does not
send receiver configuration commands because the supported models use
different settings and protocols. The [ZED-F9P integration manual](https://content.u-blox.com/sites/default/files/ZED-F9P_IntegrationManual_UBX-18010802.pdf)
describes stationary base mode, survey-in, reference-position messages, and
RTCM output configuration for that receiver family.

After setup, use these commands to check the Pi-side services and stream:

```bash
# Confirm services are active
sudo systemctl status str2str rtk-dashboard nginx

# Confirm which TCP port str2str selected
cat /var/lib/rtk-base/stream-port
sudo ss -ltnp

# Inspect receiver and conversion messages
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
