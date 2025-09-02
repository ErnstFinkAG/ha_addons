from __future__ import annotations

import logging
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, QUESTION, DEFAULT_HOST
from .api import MK5SClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data.get("host", DEFAULT_HOST)
    interval = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)

    session = aiohttp_client.async_get_clientsession(hass)
    client = MK5SClient(host, QUESTION, session)

    async def _async_update():
        try:
            return await client.snapshot()
        except Exception as e:
            raise UpdateFailed(str(e)) from e

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="mk5s_coordinator",
        update_method=_async_update,
        update_interval=timedelta(seconds=interval),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
