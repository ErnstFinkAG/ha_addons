# MK5S Client (Home Assistant Add-on)

Polls Atlas Copco **MK5s Touch** air compressor controllers and publishes **MQTT sensors** for the confirmed-good data points:

- **Pressure (bar)** – from `0x3002:01` (HiU16 ÷ 1000)
- **Motor starts** – from `0x3007:03` (LoU16)
- **Load cycles** – from `0x3007:04` (LoU16)

Features
--------
- Multiple controllers (comma-separated), each with its own interval/timeout/verbose.
- Per-host **QUESTION** override (comma-separated) or a global default.
- MQTT **Auto Discovery** for Home Assistant (under `homeassistant/…` by default).
- Retained states and per-host availability (`online`/`offline`).

## Configuration

All list-like options are **comma-separated strings** of equal (or compatible) lengths.
If a list is shorter, its last value is reused for remaining hosts.

| Option            | Type | Example                                  | Notes |
|-------------------|------|------------------------------------------|-------|
| `ip_list`         | str  | `10.60.23.11,10.60.23.12`                | IPs of MK5s controllers |
| `name_list`       | str  | `compressor_a,compressor_b`              | Used for MQTT topics & unique IDs |
| `interval_list`   | str  | `10,15`                                  | Polling interval in seconds |
| `timeout_list`    | str  | `5,5`                                    | HTTP timeout in seconds |
| `verbose_list`    | str  | `true,false`                              | Log Question/Answer for the host |
| `question`        | str  | *(long hex)*                              | Global QUESTION hex string |
| `question_list`   | str  | `,<custom for host2>`                     | Per-host QUESTION; empty = use global |
| `mqtt_host`       | str  | `localhost`                               | MQTT broker |
| `mqtt_port`       | int  | `1883`                                    | MQTT port |
| `mqtt_user`       | str  | `mqtt_user`                               | MQTT username |
| `mqtt_password`   | str  | `mqtt_password`                           | MQTT password |
| `discovery_prefix`| str  | `homeassistant`                           | Discovery prefix |

## MQTT Layout

For each host (slugified controller name `slug`):

- Discovery (retained):
  - `homeassistant/sensor/<slug>/pressure_bar/config`
  - `homeassistant/sensor/<slug>/motor_starts/config`
  - `homeassistant/sensor/<slug>/load_cycles/config`
- State (retained):
  - `<slug>/pressure_bar`
  - `<slug>/motor_starts`
  - `<slug>/load_cycles`
- Availability (retained):
  - `<slug>/availability`

## Notes

- The add-on uses `host_network: true` to reach the controller at `http://<ip>/cgi-bin/mkv.cgi`.
- Dependencies are installed from Alpine packages to avoid PEP 668 (`py3-requests`, `py3-paho-mqtt`).
