from __future__ import annotations

from typing import Optional

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

SENSORS = [
    ("pressure_bar", "MK5S Pressure", "bar", SensorDeviceClass.PRESSURE),
    ("motorstarts", "MK5S Motorstarts", None, None),
    ("lastspiele", "MK5S Lastspiele", None, None),
    ("luefterstarts", "MK5S Lüfterstarts", None, None),
    ("duty_1_20_pct", "MK5S Duty 1–20%", "%", None),
    ("duty_20_40_pct", "MK5S Duty 20–40%", "%", None),
    ("duty_40_60_pct", "MK5S Duty 40–60%", "%", None),
    ("duty_60_80_pct", "MK5S Duty 60–80%", "%", None),
    ("duty_80_100_pct", "MK5S Duty 80–100%", "%", None),
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    data = hass.data[DOMAIN][entry.entry_id]
    coord = data["coordinator"]
    host = entry.data.get("host", "unknown")
    entities = [MK5SSensor(coord, entry.entry_id, key, name, unit, device_class, host) for key, name, unit, device_class in SENSORS]
    async_add_entities(entities)

class MK5SSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry_id: str, key: str, name: str, unit: Optional[str], device_class: Optional[SensorDeviceClass], host: str):
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        if device_class:
            self._attr_device_class = device_class
        self._attr_device_info = {
            "identifiers": {(DOMAIN, host)},
            "name": f"MK5S @ {host}",
            "manufacturer": "Unknown",
            "model": "MK5S",
        }

    @property
    def native_value(self):
        val = self.coordinator.data.get(self._key)
        if val is None:
            return None
        if self._key == "pressure_bar":
            return round(float(val), 3)
        if self._key.startswith("duty_"):
            return round(float(val), 1)
        return val
