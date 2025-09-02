from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from .const import DOMAIN, DEFAULT_HOST, DEFAULT_SCAN_INTERVAL

DATA_SCHEMA = vol.Schema(
    {
        vol.Optional("host", default=DEFAULT_HOST): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("scan_interval", default=DEFAULT_SCAN_INTERVAL): vol.All(int, vol.Range(min=3, max=300)),
    }
)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=f"MK5S ({user_input['host']})", data=user_input)
        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

    async def async_step_import(self, user_input):
        return await self.async_step_user(user_input)

class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=OPTIONS_SCHEMA,
        )
