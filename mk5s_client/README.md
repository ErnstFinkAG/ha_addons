# Atlas Copco MK5s Touch — Home Assistant Add‑on

**Client script:** `mk5s_client.py v0.8.1` (PS‑sequence parity + entity_id fix)

This add‑on mirrors the proven PowerShell approach with **one single QUESTION** and strict token parsing. It also fixes MQTT Discovery so entity_ids aren’t double‑prefixed in Home Assistant.

---

## Quick start

1. Copy `mk5s_client.py` (v0.8.1) into the add‑on.
2. Configure `/data/options.json` (see **Configuration** below).
3. Start the add‑on. Home Assistant auto‑discovers the device and sensors.

> If you previously had duplicates like `sensor.<slug>_<slug>_vsd_80_100`, v0.8.1 publishes empty retained configs to legacy topics so HA removes them. If they linger, reload MQTT in HA (Settings → Devices & Services → MQTT → Reload) or restart HA.

---

## How it works (PS‑parity)

- The client posts **one single `QUESTION`** to `/cgi-bin/mkv.cgi` using the exact hex sequence below.
- The controller replies with a stream of tokens:
  - Each token is either `X` (unavailable) **or** an 8‑hex `UInt32` word.
  - Parsing is **sequential**: the N‑th token corresponds to the N‑th key of the QUESTION.
- Tokens are mapped to HA sensors and **decoded** per the rules in the table.
- If a field for HA is `X`, the client performs a **single‑pair fallback read** just for that pair (e.g., `QUESTION=30070D`).

### Single‑shot QUESTION (exact order)
```
300201300203300205300208
30030130030230030a
30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f300714300715300718300722300723300724
30210130210530210a
300501300502300504300505300507300508300509
300e03300e04300e2a300e88
31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f311360311361311362311363311364311365311366311367
31140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412
300901300906300907
300108
```

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
| `service_3000_hours`     | 3009.06  | UInt32 | **3000 − (UInt32/3600)** → **h**              | Remaining hours |
| `service_6000_hours`     | 3009.07  | UInt32 | **6000 − (UInt32/3600)** → **h**              | Remaining hours |
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
