"""Constants for the RTK-Base integration."""

from homeassistant.const import Platform

DOMAIN = "rtk_base"
DEFAULT_HOST = "http://rtk-base.local"
UPDATE_INTERVAL_SECONDS = 30
PLATFORMS = [Platform.SENSOR]

STAT_FIELDS = (
    "temp_c",
    "cpu",
    "mem_pct",
    "memory_used_bytes",
    "disk_pct",
    "uptime_seconds",
    "load_1m",
    "load_5m",
    "load_15m",
)
