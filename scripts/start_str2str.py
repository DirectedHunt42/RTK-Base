#!/usr/bin/env python3
"""Start str2str on the first available RTK-Base TCP output port."""

import os
import socket
import sys
from pathlib import Path


STR2STR = "/usr/bin/str2str"
PORT_FILE = Path("/var/lib/rtk-base/stream-port")
DEFAULT_PORT = 2101
PORT_LIMIT = 2120
DEVICE = os.environ.get("RTK_BASE_GNSS_DEVICE", "")
POSITION = os.environ.get("RTK_BASE_POSITION", "").split()


def str2str_args(port: int) -> list[str]:
    # Convert UBX raw observations to RTCM 3. Station coordinates are needed
    # for RTCM 1005; do not advertise a fabricated (0, 0, 0) reference point.
    messages = "1077(1),1087(1),1097(1),1127(1),1230(10)"
    # RTKLIB's serial stream handler prefixes the port with /dev/, so pass a
    # device path relative to /dev even when setup stored an absolute path.
    serial_device = DEVICE.removeprefix("/dev/")
    args = [STR2STR, "-in", f"serial://{serial_device}:115200#ubx"]
    if len(POSITION) == 3:
        try:
            latitude, longitude, height = map(float, POSITION)
        except ValueError as exc:
            raise ValueError("RTK_BASE_POSITION must contain latitude longitude height") from exc
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("RTK_BASE_POSITION latitude/longitude is out of range")
        messages = "1005(10)," + messages
        args.extend(["-p", str(latitude), str(longitude), str(height)])
    elif POSITION:
        raise ValueError("RTK_BASE_POSITION must contain latitude longitude height")
    args.extend(["-msg", messages, "-out", f"tcpsvr://:{port}#rtcm3"])
    return args


def main() -> int:
    if not DEVICE or not Path(DEVICE).exists():
        print(f"GNSS receiver device is missing: {DEVICE or '(not configured)'}", file=sys.stderr)
        return 1
    if not os.path.isfile(STR2STR) or not os.access(STR2STR, os.X_OK):
        print(f"str2str executable not found: {STR2STR}", file=sys.stderr)
        return 1

    selected_port = None
    for port in range(DEFAULT_PORT, PORT_LIMIT + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("0.0.0.0", port))
            selected_port = port
            break
        except OSError:
            continue

    if selected_port is None:
        print(f"No free RTCM TCP port in range {DEFAULT_PORT}-{PORT_LIMIT}", file=sys.stderr)
        return 1

    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = PORT_FILE.with_suffix(".tmp")
    temp_file.write_text(f"{selected_port}\n", encoding="ascii")
    os.replace(temp_file, PORT_FILE)
    try:
        args = str2str_args(selected_port)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Starting str2str: {DEVICE} -> RTCM 3 on TCP port {selected_port}", flush=True)
    os.execv(STR2STR, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
