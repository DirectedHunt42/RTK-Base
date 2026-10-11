<p align="center">
  <img src="dashboard/static/icons/base-station.svg" alt="RTK-Base station" width="72" height="72">
</p>

<h1 align="center">RTK-Base</h1>

<p align="center">A Raspberry Pi RTK base station with an RTCM correction stream and a live GNSS diagnostics dashboard.</p>

<p align="center"><strong>Dashboard version 0.11.1</strong></p>

<p align="center">
  <img src="dashboard/static/icons/satellite-gps.svg" alt="GPS" width="28" height="28" title="GPS">
  <img src="dashboard/static/icons/satellite-glonass.svg" alt="GLONASS" width="28" height="28" title="GLONASS">
  <img src="dashboard/static/icons/satellite-galileo.svg" alt="Galileo" width="28" height="28" title="Galileo">
  <img src="dashboard/static/icons/satellite-beidou.svg" alt="BeiDou" width="28" height="28" title="BeiDou">
  <img src="dashboard/static/icons/satellite-qzss.svg" alt="QZSS" width="28" height="28" title="QZSS">
  <img src="dashboard/static/icons/satellite-sbas.svg" alt="SBAS" width="28" height="28" title="SBAS">
  <img src="dashboard/static/icons/satellite-navic.svg" alt="NavIC" width="28" height="28" title="NavIC">
  <img src="dashboard/static/icons/satellite-imes.svg" alt="IMES" width="28" height="28" title="IMES">
</p>

## Overview

RTK-Base connects a u-blox GNSS receiver to a Raspberry Pi and forwards the
receiver's RTCM 3 corrections to RTK clients over TCP. Its web dashboard shows
the receiver and satellite data alongside system, network, and stream status.

The dashboard includes a receiver map, satellite sky plot, constellation
indicators, signal and position details, an interactive GNSS orbital view,
network diagnostics, logs, and installed configuration downloads. You can
switch the receiver between correction streaming and GPS telemetry from the
dashboard.

## Hardware and receiver requirements

- Raspberry Pi running Raspberry Pi OS with internet access during setup.
- u-blox GNSS receiver, such as a ZED-F9P or NEO-M8P.
- GNSS antenna with a clear view of the sky.
- USB connection between receiver and Pi.

The receiver must be configured separately to provide RTCM 3 output for base
operation. For an RTK base, set a surveyed or fixed base position (or perform a
survey-in), enable RTCM observation messages for the constellations in use, and
include a reference position message such as RTCM 1005. Keep the antenna
stationary while surveying in. Receiver configuration varies by model; the
[CubePilot HERE 3 manual](https://github.com/CubePilot/cubepilot-docs/blob/master/here-3/here-3-manual.md)
covers its base survey and RTCM status workflow.

## Install

Connect the receiver before setup. The installer records its stable
`/dev/serial/by-id` path when available, falling back to another detected serial
device if needed.

```bash
git clone https://github.com/DirectedHunt42/RTK-Base.git
cd RTK-Base
chmod +x setup.sh
sudo ./setup.sh
```

Setup installs the packages listed in [`packages.json`](packages.json),
including RTKLIB (`str2str`), GPSD, Flask, and nginx. It configures the system
services and nginx, then starts the correction stream and dashboard. When
setup completes, open `http://<pi-ip>` in a browser on the same network.

The dashboard runs on port **80**. The stream uses TCP port **2101** when it is
available; if it is occupied, RTK-Base tries ports **2102–2120** and selects
the first available one. The active port is shown in the dashboard's System
panel and in setup's completion message.

## Connect an RTK client

In Mission Planner, open **Setup → Optional Hardware → RTK/GPS Inject**, choose
**TCP Client**, and enter the Pi's IP address and active RTCM port. Leave both
NTRIP options unchecked. You can find the active port in the dashboard's
System panel or on the Pi with:

```bash
cat /var/lib/rtk-base/stream-port
```

## Operating modes

The receiver has one serial connection, so `str2str` and GPSD use it in
separate modes. Switch modes with the **GNSS / GPS** controls in the dashboard.

| Mode | Receiver owner | What it does |
| --- | --- | --- |
| RTCM corrections | RTKLIB `str2str` | Forwards the receiver's RTCM output to TCP clients. This is the normal mode for RTK corrections. |
| GPS telemetry | GPSD | Reads receiver position, fix, and satellite information for the dashboard. The RTCM stream pauses. |

Return to **RTCM corrections** before connecting an RTK client. A running
service or open port alone does not confirm that the receiver has a valid fix
or is sending usable RTCM messages.

## Dashboard guide

The dashboard refreshes its diagnostics automatically. Click a panel heading
to collapse or expand it; the browser remembers your panel layout.

- **System and Resources** show host details and Raspberry Pi resource usage.
- **RTK Stream Health** and **RX / TX Data Flow** show stream and network
  activity.
- **GNSS / GPS** displays the active mode and provides the mode controls.
- **Receiver Location**, **GNSS Constellations**, and **Satellite Sky Map**
  present GPSD telemetry when GPS telemetry mode is active.
- **Network**, **USB Devices**, and **Serial Devices** help inspect the Pi and
  receiver connection.
- **Repository File Tree** lists files in the configured checkout.
- **GNSS Orbital View** can be dragged to rotate and scrolled to zoom. Hover
  over a satellite for its signal and sky details. Its satellite positions and
  trails are approximate: GPSD supplies azimuth and elevation, and the view
  uses representative orbit heights instead of live satellite ephemerides.

The receiver map uses OpenStreetMap tiles and needs an internet connection.
The orbital view's continent outlines use
[Natural Earth 1:110m Land](https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/)
(public domain). Its background star positions and proper motions use
[ESA Gaia Data Release 3](https://www.cosmos.esa.int/web/gaia/dr3) (ESA/Gaia/DPAC).

- <img src="dashboard/static/icons/files-config.svg" alt="Files and configuration" width="24" height="24"> **Files** opens selected logs and installed configuration downloads.
- <img src="dashboard/static/icons/readme.svg" alt="README" width="24" height="24"> **README** opens this guide.
- <img src="dashboard/static/icons/license.svg" alt="Licence" width="24" height="24"> **Licence** displays the project licence.
- <img src="dashboard/static/icons/update.svg" alt="Update" width="24" height="24"> **Update** pulls the latest repository version, reruns setup, and checks for Raspberry Pi OS package upgrades. If upgrades are available, the dashboard asks whether to install them.
- <img src="dashboard/static/icons/reboot.svg" alt="Reboot" width="24" height="24"> **Reboot** reboots the Pi.

**Update note:** the updater runs `git reset --hard` in the configured checkout
before pulling. This discards tracked local changes in that checkout. Back up
any changes you need before using the dashboard updater.

## Services and ports

| Service / endpoint | Address or port | Purpose |
| --- | --- | --- |
| Dashboard | `http://<pi-ip>` (TCP 80) | Diagnostics and receiver telemetry |
| RTCM stream | `tcp://<pi-ip>:<active-port>` (TCP 2101–2120) | Corrections for RTK clients |
| GPSD | Local TCP 2948 | Receiver telemetry while GPS telemetry mode is active |
| Dashboard application | Local TCP 8080 | Flask app behind nginx |

Systemd services are `str2str`, `rtk-dashboard`, and `rtk-gpsd`. The GPSD unit
starts when telemetry mode is selected; it conflicts with the `str2str`
service.

## Check status and logs

```bash
# Check service state
sudo systemctl status str2str rtk-dashboard nginx

# Check the selected stream port and listening sockets
cat /var/lib/rtk-base/stream-port
sudo ss -ltnp

# Inspect recent stream and dashboard logs
sudo journalctl -u str2str -n 50 --no-pager
sudo journalctl -u rtk-dashboard -n 50 --no-pager
```

These checks show whether Pi services are running. To confirm the receiver is
producing usable corrections, also check its fix and RTCM output configuration.

## Troubleshooting

| Symptom | Checks |
| --- | --- |
| Setup cannot find the receiver | Connect it before setup. Check `ls -l /dev/serial/by-id/` and `ls /dev/ttyACM* /dev/ttyUSB*`. |
| Dashboard has no telemetry | Select GPS telemetry mode, check the antenna and receiver output, and inspect `sudo journalctl -u rtk-gpsd -n 100 --no-pager`. |
| Client cannot connect | Switch to RTCM corrections, use the active port from the System panel or `/var/lib/rtk-base/stream-port`, and check `sudo ss -ltnp`. |
| Client connects but has no RTK solution | Verify the receiver has a valid fix and configured base position, and that it outputs observation and reference-position RTCM messages. |
| A service is failing | Inspect its journal with `sudo journalctl -u <service> -n 100 --no-pager`, replacing `<service>` with `str2str`, `rtk-dashboard`, `rtk-gpsd`, or `nginx`. |
| Need downloadable diagnostics | Use the Files action in the dashboard to access selected logs and installed configuration files. |

## Repository layout

- `dashboard/` contains the Flask dashboard, browser assets, icons, and map and
  orbital-view data.
- `scripts/receiver/` contains receiver startup and operating-mode scripts.
- `scripts/maintenance/` contains status, download, and update scripts.
- `services/systemd/` and `services/nginx/` contain service and web-proxy
  configuration.
- [`setup.sh`](setup.sh) installs the dashboard, scripts, services, and proxy.
- [`packages.json`](packages.json) lists the APT packages installed by setup.
- [`LICENSE.txt`](LICENSE.txt) contains the project licence.

Made for practical RTK base station monitoring in the field.
