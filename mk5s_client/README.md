# MK5S Client (confirmed-good)

This add-on polls an MK5S controller and publishes **confirmed-good** sensors to Home Assistant.

**Baked defaults**
- Host: `10.60.23.11`
- Fixed QUESTION frame: constant, sent as-is
- Sensors:
  - `sensor.mk5s_pressure_bar` — 0x3002/0x01 HiU16 / 1000
  - `sensor.mk5s_motorstarts`  — 0x3007/0x03 LoU16
  - `sensor.mk5s_lastspiele`   — 0x3007/0x04 LoU16
  - `sensor.mk5s_luefterstarts`— 0x3007/0x0B UInt32

The add-on uses the Home Assistant Core API (via Supervisor) to create/update states — no MQTT required.

## Options
- `host` (string) — MK5S IP, default `10.60.23.11`
- `scan_interval` (int) — seconds between polls, default `15`
- `request_timeout` (int) — HTTP timeout in seconds, default `5`
- `log_raw_frames` (bool) — log Question/Answer strings to the add-on log, default `true`

## Repository installation
1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Add your GitHub repo URL, e.g. `https://github.com/ErnstFinkAG/ha_addons`.
3. Find **MK5S Client (confirmed-good)** and install.
4. Start the add-on. (Optional) Adjust options.
5. The sensors will appear under **Developer Tools → States** and can be added to dashboards.

## Notes
- Only confirmed-good mappings are included. When additional addresses are confirmed, we can extend the add-on.
- The add-on logs each raw frame when `log_raw_frames` is enabled — helpful for troubleshooting.
