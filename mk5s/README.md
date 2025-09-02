# MK5S Home Assistant Integration

A lightweight custom integration that polls an MK5S controller and exposes *confirmed-good* values as sensors.

### Exposed sensors
- `sensor.mk5s_pressure_bar` — from 0x3002/0x01 (HiU16 / 1000)
- `sensor.mk5s_motorstarts` — from 0x3007/0x03 (LoU16)
- `sensor.mk5s_lastspiele` — from 0x3007/0x04 (LoU16)
- `sensor.mk5s_luefterstarts` — from 0x3007/0x0B (UInt32)
- `sensor.mk5s_duty_1_20_pct` — 0x3007/0x05 (HiU16/10)
- `sensor.mk5s_duty_20_40_pct` — 0x3007/0x06 (HiU16/10)
- `sensor.mk5s_duty_40_60_pct` — 0x3007/0x07 (HiU16/10)
- `sensor.mk5s_duty_60_80_pct` — 0x3007/0x08 (HiU16/10)
- `sensor.mk5s_duty_80_100_pct` — 0x3007/0x09 (HiU16/10)

### Install
1. Copy `custom_components/mk5s/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Add the integration via **Settings → Devices & Services → Add Integration → MK5S**.
   - Host defaults to `10.60.23.11` (see `const.py`).
   - Poll interval defaults to 10s (configurable in integration options).

### Notes
- Uses a fixed QUESTION frame matching the controller's WebUI calls.
- Only decodes the values we have validated.
- No cloud; local polling via `http://<host>/cgi-bin/mkv.cgi`.
