# RTK-Base

DIY RTK base station for a Raspberry Pi and u-blox GNSS receiver. The Pi reads
the receiver and serves RTCM corrections over TCP for clients such as Mission
Planner.

## Features

- Streams RTCM 3 over TCP on port **2101**
- Starts the RTCM stream and diagnostics dashboard at boot
- Live system and network diagnostics, plus switchable GPS telemetry
- Dashboard available on the standard HTTP port

## Hardware

- Raspberry Pi with Raspberry Pi OS
- u-blox GNSS receiver (such as F9P or M8P) connected by USB

## Install

```bash
git clone https://github.com/YOUR_USERNAME/rtk-base.git
cd rtk-base
sudo ./setup.sh
```

After setup, open `http://<pi-ip>` in a browser. For example, if the Pi's
address is `192.168.0.41`, visit `http://192.168.0.41`.

## Connections

| Service | Address | Purpose |
| --- | --- | --- |
| RTCM stream | `tcp://<pi-ip>:2101` | Correction data for Mission Planner |
| Dashboard | `http://<pi-ip>` (port 80) | Live diagnostics |

In Mission Planner, open **Setup → Optional Hardware → RTK/GPS Inject** and
select **TCP Client**. Enter the Pi's IP address and port **2101**. Leave both
NTRIP options unchecked.

## GPS and stream modes

The dashboard starts in **RTCM corrections** mode. Use the controls in the
GNSS / GPS card to switch between:

- **RTCM corrections**: `str2str` owns the receiver port and serves data on
  port 2101.
- **GPS telemetry**: GPSD owns the receiver port and the dashboard displays
  fix type, position, altitude, speed, and satellites used/visible.

The receiver exposes one configured serial port, so these modes are exclusive.
RTCM corrections pause while GPS telemetry is selected. Switching back restarts
the RTCM stream. Setup installs and configures both services and grants the
dashboard permission to switch only between these two modes. The system GPSD
socket service is disabled so it cannot claim the receiver port independently.
Anyone with access to the dashboard can change the active mode.

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
