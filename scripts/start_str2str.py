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


def str2str_args(port: int) -> list[str]:
    # RTKLIB's serial stream handler prefixes the port with /dev/, so pass a
    # device path relative to /dev even when setup stored an absolute path.
    # HERE 3 base receivers already output RTCM; forward it unchanged instead
    # of asking RTKLIB to decode it as UBX and generate a second RTCM stream.
    serial_device = DEVICE.removeprefix("/dev/")
    return [
        STR2STR,
        "-in",
        f"serial://{serial_device}:115200",
        "-out",
        f"tcpsvr://:{port}",
    ]


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
    args = str2str_args(selected_port)
    print(f"Starting str2str: {DEVICE} -> RTCM 3 on TCP port {selected_port}", flush=True)
    os.execv(STR2STR, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
