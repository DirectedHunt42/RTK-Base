"""RTK-Base Home Assistant integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import RTKBaseCoordinator

if TYPE_CHECKING:
    RTKBaseConfigEntry = ConfigEntry[RTKBaseCoordinator]
else:
    RTKBaseConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: RTKBaseConfigEntry) -> bool:
    """Set up RTK-Base from a config entry."""
    coordinator = RTKBaseCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RTKBaseConfigEntry) -> bool:
    """Unload RTK-Base platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
