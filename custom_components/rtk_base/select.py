"""Mode selector for RTK-Base."""

from __future__ import annotations

import asyncio

import aiohttp
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RTKBaseConfigEntry
from .const import DOMAIN
from .coordinator import RTKBaseCoordinator

MODE_OPTIONS = ["corrections", "telemetry"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RTKBaseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the RTK-Base receiver mode selector."""
    coordinator: RTKBaseCoordinator = entry.runtime_data
    async_add_entities([RTKBaseModeSelect(coordinator, entry)])


class RTKBaseModeSelect(CoordinatorEntity[RTKBaseCoordinator], SelectEntity):
    """Switch the receiver between RTCM corrections and GPSD telemetry."""

    _attr_has_entity_name = True
    _attr_translation_key = "mode"
    _attr_icon = "mdi:swap-horizontal"
    _attr_options = MODE_OPTIONS

    def __init__(
        self,
        coordinator: RTKBaseCoordinator,
        entry: RTKBaseConfigEntry,
    ) -> None:
        """Initialize the selector."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name="RTK-Base",
            manufacturer="RTK-Base",
            model="Raspberry Pi",
        )

    @property
    def current_option(self) -> str | None:
        """Return the current supported receiver mode, if one is active."""
        mode = self.coordinator.data.get("mode")
        return mode if mode in MODE_OPTIONS else None

    async def async_select_option(self, option: str) -> None:
        """Request a receiver mode change through the Pi's existing API."""
        session = async_get_clientsession(self.coordinator.hass)
        try:
            async with session.post(
                f"{self.coordinator.base_url}/api/mode",
                json={"mode": option},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                try:
                    result = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as err:
                    raise HomeAssistantError(
                        "The RTK-Base mode endpoint returned an invalid response"
                    ) from err
                if response.status >= 400:
                    message = result.get("error") if isinstance(result, dict) else None
                    raise HomeAssistantError(message or "RTK-Base could not switch receiver mode")
        except HomeAssistantError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise HomeAssistantError("Could not connect to RTK-Base to switch receiver mode") from err

        if not isinstance(result, dict) or result.get("mode") != option:
            raise HomeAssistantError("RTK-Base did not enter the requested receiver mode")
        await self.coordinator.async_request_refresh()
