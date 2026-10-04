# RTK-Base

Simple, reliable DIY RTK Base Station for Raspberry Pi + u-blox GNSS receiver.

## Features

- Streams RTCM 3 (MSM7) over TCP on port **2101**
- Automatic start on boot via systemd
- Live web diagnostics dashboard (terminal theme)
- One-command setup

## Hardware

- Raspberry Pi (any recent model)
- u-blox GNSS receiver (F9P / M8P etc.) connected via USB

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/rtk-base.git
cd rtk-base
sudo ./setup.sh