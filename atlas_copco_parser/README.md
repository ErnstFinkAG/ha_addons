# atlas_copco_parser — Home Assistant Add‑on

---

## Full encoding list (MK5s Touch)

Legend:
- **HiU16** = upper 16 bits of the 32‑bit word (unsigned)  
- **LoU16** = lower 16 bits (unsigned)  
- **UInt32** = full 32‑bit unsigned integer  
- Seconds → hours shown as “/ 3600”  
- VSD buckets: `% = UInt32 / 65,831,881 × 100`

| HA key                   | Pair     | Part   | Decode → Unit                                 | Comment |
|---                       |---       |---     |---                                            |---|
| `pressure_bar`           | 3002.01  | HiU16  | **HiU16 / 1000** → **bar**                    |  |
| `element_outlet`         | 3002.03  | HiU16  | **HiU16 / 10** → **°C**                       |  |
| `ambient_air`            | 3002.05  | HiU16  | **HiU16 / 10** → **°C**                       |  |
| `controller_temperature` | 3002.08  | HiU16  | **HiU16 / 10** → **°C**                       |  |
| `running_hours`          | 3007.01  | UInt32 | **UInt32 / 3600** → **h**                     |  |
| `motor_starts`           | 3007.03  | LoU16  | **LoU16**                                     |  |
| `load_cycles`            | 3007.04  | LoU16  | **LoU16**                                     |  |
| `vsd_1_20`               | 3007.05  | UInt32 | **(UInt32 / 65,831,881) × 100** → **%**       |  |
| `vsd_20_40`              | 3007.06  | UInt32 | **(UInt32 / 65,831,881) × 100** → **%**       |  |
| `vsd_40_60`              | 3007.07  | UInt32 | **(UInt32 / 65,831,881) × 100** → **%**       |  |
| `vsd_60_80`              | 3007.08  | UInt32 | **(UInt32 / 65,831,881) × 100** → **%**       |  |
| `vsd_80_100`             | 3007.09  | UInt32 | **(UInt32 / 65,831,881) × 100** → **%**       |  |
| `fan_starts`             | 3007.0B  | UInt32 | **UInt32**                                     |  |
| `accumulated_volume`     | 3007.0C  | UInt32 | **UInt32 × 1000** → **m³**                    |  |
| `module_hours`           | 3007.0D  | UInt32 | **UInt32 / 3600** → **h**                     |  |
| `emergency_stops`        | 3007.0E  | UInt32 | **UInt32**                                     |  |
| `direct_stops`           | 3007.0F  | UInt32 | **UInt32**                                     |  |
| `recirculation_starts`   | 3007.14  | UInt32 | **UInt32**                                     |  |
| `recirculation_failures` | 3007.15  | UInt32 | **UInt32**                                     |  |
| `low_load_hours`         | 3007.18  | UInt32 | **UInt32 / 3600** → **h**                     |  |
| `available_hours`        | 3007.22  | UInt32 | **UInt32 / 3600** → **h**                     |  |
| `unavailable_hours`      | 3007.23  | UInt32 | **UInt32 / 3600** → **h**                     |  |
| `emergency_stop_hours`   | 3007.24  | UInt32 | **UInt32 / 3600** → **h**                     |  |
| `rpm_actual`             | 3021.01  | HiU16  | **HiU16** → **rpm**                           |  |
| `rpm_requested`          | 3021.01  | LoU16  | **LoU16** → **rpm**                           |  |
| `current`                | 3021.05  | LoU16  | **LoU16** → **A**                             |  |
| `flow`                   | 3021.0A  | HiU16  | **HiU16** → **%**                             |  |
| `fan_motor` *(binary)*   | 3005.01  | HiU16  | **1 = ON**, **0 = OFF**                       | Published as `binary_sensor` |
| `service_a`     | 3009.06  | UInt32 | **A Service: 3000 − (UInt32/3600)** → **h**              | Remaining hours |
| `service_b`     | 3009.07  | UInt32 | **B Service: 6000 − (UInt32/3600)** → **h**              | Remaining hours |
| `machine_status`         | 3001.08  | UInt32 | **UInt32**                                    | `5 = standby`, `28 = load` |

---

## Configuration (`/data/options.json`)

| Key | Type | Example | Notes |
|---|---|---|---|
| `ip_list` | string (CSV) | `"10.60.23.11"` | One or more controllers |
| `name_list` | string (CSV) | `"eftool-bw-b2-air1"` | Friendly device names |
| `interval_list` | string (CSV) | `"10"` | Poll interval (s) |
| `timeout_list` | string (CSV) | `"5"` | HTTP timeout (s) |
| `verbose_list` | string (CSV) | `"true"` | Verbose logging per host |
| `mqtt_host` | string | `"core-mosquitto"` | MQTT broker |
| `mqtt_port` | number | `1883` |  |
| `mqtt_user` | string | `""` | Optional |
| `mqtt_password` | string | `""` | Optional |
| `discovery_prefix` | string | `"homeassistant"` | HA MQTT discovery prefix |
| `scaling_overrides` | JSON string | `"{}"` | Optional per‑sensor multiplier (applied after decode) |

> CSV values are matched **by position** per host (last value repeats).

Example:
```json
{
  "ip_list": "10.60.23.11",
  "name_list": "eftool-bw-b2-air1",
  "interval_list": "10",
  "timeout_list": "5",
  "verbose_list": "true",
  "mqtt_host": "core-mosquitto",
  "mqtt_port": 1883,
  "mqtt_user": "",
  "mqtt_password": "",
  "discovery_prefix": "homeassistant",
  "scaling_overrides": "{}"
}
```

---

## MQTT Discovery (entity_id fix)

- **Node ID (topic):** device slug, e.g. `eftool_bw_b2_air1`  
- **Object ID:** just the sensor key, e.g. `vsd_80_100`  
- **Unique ID:** `mk5s:<device_slug>:<key>`  
- **State topic:** `<device_slug>/<key>`

`homeassistant/<platform>/<device_slug>/<device_slug>_<key>/config` (emptied, retained),
then publishes the correct one:
`homeassistant/<platform>/<device_slug>/<key>/config`.

---
