# Home Assistant Add-on — Atlas Copco MK5s Client

Poll Atlas Copco **MK5s Touch** controllers over HTTP and publish their telemetry to MQTT with **Home Assistant MQTT Discovery**.  
This add-on is designed for Supervisor-based installs (HAOS / Supervised).

---

## What it does

- Sends `POST` requests to the controller at `http://<ip>/cgi-bin/mkv.cgi` with a hex **QUESTION**.
- Decodes the response per register (“index.subindex”, e.g. `3007.01`) and publishes sensor states.
- Auto-creates entities in Home Assistant using MQTT Discovery (one **device** per controller).
- **Robust polling:** groups subindices by **index** (e.g., all `3007.*` together) to ensure the reply tokens align 1:1, with a safe per-pair fallback.
- **Verbose logs:** optional per-host logs show (a) the QUESTION, (b) raw/clean reply, and (c) for every sensor: raw 8-hex, the extracted integer (Hi/Lo/U32), and the calculated value with units.
- **Scaling overrides:** per-sensor multiplicative override to adapt to model differences (e.g., hours vs. seconds on your unit).

---

## Requirements

- An MQTT broker accessible by Home Assistant (e.g., the Mosquitto add-on).
- Network access from the HA host to each MK5s controller (the add-on runs in `host_network: true`).
- MK5s firmware exposing `cgi-bin/mkv.cgi` on HTTP.

---

## Installation

1. In **Settings → Add-ons → Add-on Store → ⋮ (top-right) → Repositories**, add your repository URL that contains this add-on (`mk5s_client`).
2. Open **MK5s Client** and click **Install**.
3. Configure (see below) and click **Start**.

> Entities will appear automatically via MQTT Discovery under the device: **Atlas Copco — MK5s Touch**.

---

## Configuration

The add-on supports monitoring **one or many controllers** in parallel. Options ending with `_list` accept a comma-separated list. If a list is shorter than `ip_list`, the **last non-empty value** is used for the remaining hosts.

### Example — single controller

```yaml
ip_list: "10.60.23.11"
name_list: "compressor_a"
interval_list: "10"
timeout_list: "5"
verbose_list: "true"

mqtt_host: "localhost"
mqtt_port: 1883
mqtt_user: "mqtt_user"
mqtt_password: "mqtt_password"
discovery_prefix: "homeassistant"

# Optional: user QUESTION(s). Leave empty to let the add-on build the right one automatically.
question: ""
question_list: ""

# Optional: fix scaling on models that already report hours (etc.).
# Example: treat low_load_hours as hours (undo ÷3600): multiply by 3600
scaling_overrides: '{"low_load_hours": 3600}'
```

### Example — two controllers (mixed verbosity)

```yaml
ip_list: "10.60.23.11,10.60.23.12"
name_list: "compressor_a,compressor_b"
interval_list: "10,15"
timeout_list: "5,5"
verbose_list: "true,false"

mqtt_host: "mqtt-broker.local"
mqtt_port: 1883
mqtt_user: "ha"
mqtt_password: "secret"
discovery_prefix: "homeassistant"

question: ""          # or remove this line entirely
question_list: ""

scaling_overrides: "{}"
```

### Option reference

| Option              | Type / Format            | Default          | Notes |
|---------------------|--------------------------|------------------|------|
| `ip_list`           | CSV list                 | (required)       | One or more controller IPs. |
| `name_list`         | CSV list                 | IP address       | Friendly device names (slugified for topics). |
| `interval_list`     | CSV list of seconds      | `10`             | Poll period per host. |
| `timeout_list`      | CSV list of seconds      | `5`              | HTTP timeout per request. |
| `verbose_list`      | CSV list (`true/false`)  | `false`          | Per-host verbose logs. |
| `mqtt_host`         | string                   | `localhost`      | Broker hostname/IP. |
| `mqtt_port`         | int                      | `1883`           | Broker port. |
| `mqtt_user`         | string                   | `""`             | MQTT username (optional). |
| `mqtt_password`     | string                   | `""`             | MQTT password (optional). |
| `discovery_prefix`  | string                   | `homeassistant`  | HA MQTT discovery prefix. |
| `question`          | hex string               | *auto*           | Optional global QUESTION override. |
| `question_list`     | CSV list of hex strings  | (empty)          | Optional per-host QUESTION. |
| `scaling_overrides` | JSON object              | `{}`             | Per-sensor **multiplier** applied to the calculated value (e.g., `{"module_hours": 3600}`). |

> **About `question` / `question_list`:** the add-on builds and sends the **correct grouped QUESTION per index** automatically. If you provide a custom QUESTION, the add-on **unions** it with the required pairs so you won’t miss any sensors.

---

## Sensors

This add-on publishes the following sensors. **Key** equals the MQTT topic suffix and the HA entity id suffix. Units and device classes are set for HA.

> ⚠️ Some registers can be unsupported on certain models/firmware and may return `X` (unknown).

| Key                      | Pair     | Part | Scaling → Unit                 | Notes |
|--------------------------|----------|------|--------------------------------|-------|
| `machine_status`         | 3001.08  | U32  | raw (status enum)              | 5 = standby, 28 = load. |
| `pressure_bar`           | 3002.01  | HiU16| ÷1000 → `bar` (absolute)       | |
| `element_outlet`         | 3002.03  | HiU16| ÷10 → `°C`                     | |
| `ambient_air`            | 3002.05  | HiU16| ÷10 → `°C`                     | |
| `controller_temperature` | 3002.08  | HiU16| ÷10 → `°C`                     | |
| `fan_motor` *(binary)*   | 3005.01  | HiU16| `1/0` → `on/off`               | device_class: `running`. |
| `running_hours`          | 3007.01  | U32  | ÷3600 → `h`                    | total_increasing. |
| `motor_starts`           | 3007.03  | LoU16| raw                            | total_increasing. |
| `load_cycles`            | 3007.04  | LoU16| raw                            | total_increasing. |
| `vsd_1_20`               | 3007.05  | U32  | ÷65,831,881×100 → `%`          | |
| `vsd_20_40`              | 3007.06  | U32  | ÷65,831,881×100 → `%`          | |
| `vsd_40_60`              | 3007.07  | U32  | ÷65,831,881×100 → `%`          | |
| `vsd_60_80`              | 3007.08  | U32  | ÷65,831,881×100 → `%`          | |
| `vsd_80_100`             | 3007.09  | U32  | ÷65,831,881×100 → `%`          | |
| `fan_starts`             | 3007.0B  | U32  | raw                            | total_increasing; may be `X` on some units. |
| `accumulated_volume`     | 3007.0C  | U32  | ×1000 → `m³`                   | If your unit already reports m³, set `{"accumulated_volume": 0.001}`. |
| `module_hours`           | 3007.0D  | U32  | ÷3600 → `h`                    | If hours already, set `{"module_hours": 3600}`. |
| `emergency_stops`        | 3007.0E  | U32  | raw                            | total_increasing. |
| `direct_stops`           | 3007.0F  | U32  | raw                            | total_increasing; may be `X` on some units. |
| `recirculation_starts`   | 3007.14  | U32  | raw                            | total_increasing. |
| `recirculation_failures` | 3007.15  | U32  | raw                            | total_increasing. |
| `low_load_hours`         | 3007.18  | U32  | ÷3600 → `h`                    | If hours already, set `{"low_load_hours": 3600}`. |
| `available_hours`        | 3007.22  | U32  | ÷3600 → `h`                    | total_increasing. |
| `unavailable_hours`      | 3007.23  | U32  | ÷3600 → `h`                    | total_increasing. |
| `emergency_stop_hours`   | 3007.24  | U32  | ÷3600 → `h`                    | total_increasing. |
| `rpm_actual`             | 3021.01  | HiU16| raw → `rpm`                    | |
| `rpm_requested`          | 3021.01  | LoU16| raw → `rpm`                    | |
| `current`                | 3021.05  | LoU16| raw → `A`                      | |
| `flow`                   | 3021.0A  | HiU16| raw → `%`                      | May be `X` on some units. |
| `service_3000_hours`     | 3009.06  | U32  | `3000 - (U32 ÷ 3600)` → `h`    | Remaining hours (never below 0). |
| `service_6000_hours`     | 3009.07  | U32  | `6000 - (U32 ÷ 3600)` → `h`    | Remaining hours (never below 0). |

---

## MQTT topics

For each host, a **base slug** is derived from `name` (or IP): lowercased, spaces to `_`.

- **Availability:** `<slug>/availability` → `online` / `offline` (retained).
- **States:** `<slug>/<key>` for every sensor key above (retained).
- **Discovery:** `${discovery_prefix}/sensor/${slug}/${key}/config` (and `binary_sensor` for `fan_motor`).

Discovery payloads include `uniq_id`, unit, device/state classes, and device metadata:
```json
"dev": { "ids": ["mk5s_<slug>"], "mf": "Atlas Copco", "mdl": "MK5s Touch", "name": "<display name>" }
```

---

## Verbose logging (optional, per host)

Set `verbose_list` to `true` for a host to print detailed traces to the add-on log:

```
[mk5s:10.60.23.11] ==== decode cycle @ 2025-09-04 16:41:53 ====
[mk5s:10.60.23.11] Q[3007]=300701300703...300724
[mk5s:10.60.23.11] A[3007]_RAW='...'
[mk5s:10.60.23.11] A[3007]_CLEAN(len=...)='...' TOKENS=...
[mk5s:10.60.23.11]   token[group:3007] 3007.0D = 0454A747
[mk5s:10.60.23.11] module_hours           pair=3007.0D part=u32 raw=0454A747   int=72656711     calc=20182.0h
...
```

- `X` means the controller reported the subindex **not available** at that moment/model.
- A failed pair may be retried once via a per-pair fallback.

---

## Testing & troubleshooting

- **Direct curl test** (grouped example for `3007.*`):
  ```bash
  curl -s -X POST "http://<ip>/cgi-bin/mkv.cgi" \
       -d "QUESTION=30070130070330070430070530070630070730070830070930070B30070C30070D30070E30070F300714300715300718300722300723300724"
  ```
  The reply is a stream of tokens; each requested subindex yields either **8 hex** (`0000001C`) or a single **`X`**.

- **Entities stay `unknown`**: check broker creds, `discovery_prefix`, and that the controller IP is reachable from HA (VLAN/firewall).

- **Scaling looks off** (e.g., hours too small): use `scaling_overrides`, e.g.:
  ```yaml
  scaling_overrides: '{"module_hours": 3600, "low_load_hours": 3600}'
  ```

- **Absolute vs. gauge pressure**: `pressure_bar` is **absolute**. For gauge, create a template sensor in HA subtracting ~1.0 bar.

---

## Changelog

- **0.6.0** — 2025-09-04  
  - Grouped batch polling by **index** with strict token alignment + per-pair fallback.  
  - Expanded sensor set (VSD buckets, service timers, hours/counters, temps, RPM/current/flow, fan motor binary).  
  - Added per-sensor `scaling_overrides`.  
  - Added rich **verbose logging** (QUESTION / tokenization / raw-int-calc lines).

- **0.5.0** — initial public version for pressure, motor starts, load cycles, discovery.

---

## License & credits

MIT-style; see repository for details.  
Thanks to community contributors for MK5s register mapping and test logs.
