"""Coordinator for polling the RTK-Base system-stats API."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, STAT_FIELDS, UPDATE_INTERVAL_SECONDS

LOGGER = logging.getLogger(__name__)


class InvalidStats(Exception):
    """The endpoint did not return valid RTK-Base system statistics."""


def validate_stats(data: Any) -> dict[str, Any]:
    """Validate the stats payload while allowing unavailable measurements."""
    if not isinstance(data, dict):
        raise InvalidStats("The response is not a system-stats object")
    if not isinstance(data.get("hostname"), str) or not data["hostname"].strip():
        raise InvalidStats("The response contains no valid hostname")
    if not any(field in data for field in STAT_FIELDS):
        raise InvalidStats("The response contains no system measurements")
    for field in STAT_FIELDS:
        value = data.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidStats(f"The response contains an invalid {field} value")
        try:
            is_finite = math.isfinite(value)
        except OverflowError:
            is_finite = False
        if not is_finite:
            raise InvalidStats(f"The response contains an invalid {field} value")
    return data


async def async_fetch_stats(hass: HomeAssistant, base_url: str) -> dict[str, Any]:
    """Fetch and validate the Pi's stats."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{base_url}/api/data",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            return validate_stats(await response.json())
    except aiohttp.ContentTypeError:
        raise
    except aiohttp.ClientResponseError as err:
        raise InvalidStats(f"The stats endpoint returned HTTP {err.status}") from err
    except (ValueError, InvalidStats):
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise ConnectionError from err


class RTKBaseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll RTK-Base system statistics."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.base_url = entry.data["base_url"]

    async def _async_update_data(self) -> dict[str, Any]:
        """Retrieve the latest system statistics."""
        try:
            return await async_fetch_stats(self.hass, self.base_url)
        except ConnectionError as err:
            raise UpdateFailed("Unable to connect to the RTK-Base stats API") from err
        except (InvalidStats, aiohttp.ContentTypeError, ValueError) as err:
            raise UpdateFailed("The RTK-Base stats API returned invalid data") from err
