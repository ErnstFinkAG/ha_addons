# MK5S Client (confirmed-good)

This add-on polls a MK5S controller and publishes **confirmed-good** sensors to Home Assistant:

- `sensor.mk5s_pressure_bar` — 3002/01 HiU16 / 1000 (bar)
- `sensor.mk5s_motorstarts`  — 3007/03 LoU16 (count)
- `sensor.mk5s_lastspiele`   — 3007/04 LoU16 (count)
- `sensor.mk5s_luefterstarts`— 3007/0B UInt32 (count)

## Options
- `host`: controller IP (default `10.60.23.11`)
- `question`: fixed hex string sent as QUESTION (defaults to your long constant)
- `interval`: poll seconds (default 10)

## Build notes
Uses a Python virtualenv to avoid PEP 668 "externally managed environment" errors in Alpine.
