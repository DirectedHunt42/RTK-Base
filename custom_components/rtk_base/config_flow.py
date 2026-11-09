"""Config flow for RTK-Base."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .const import DEFAULT_HOST, DOMAIN
from .coordinator import InvalidStats, async_fetch_stats


def normalize_base_url(value: str) -> str:
    """Normalize an HTTP(S) host/address to its origin."""
    value = value.strip()
    if "://" not in value:
        value = f"http://{value}"
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as err:
        raise ValueError from err
    if (
        parsed.scheme.lower() not in ("http", "https")
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, "", "", "")).rstrip("/")


class RTKBaseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a RTK-Base device."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Validate the supplied Pi address and create an entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url = normalize_base_url(user_input["host"])
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                try:
                    stats = await async_fetch_stats(self.hass, base_url)
                except ConnectionError:
                    errors["base"] = "cannot_connect"
                except (InvalidStats, aiohttp.ContentTypeError, ValueError):
                    errors["base"] = "invalid_data"
                else:
                    await self.async_set_unique_id(stats["hostname"].strip().lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"RTK-Base ({stats['hostname']})",
                        data={"base_url": base_url},
                    )

        schema = vol.Schema(
            {
                vol.Required("host", default=DEFAULT_HOST): TextSelector(
                    TextSelectorConfig(type="url")
                )
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
