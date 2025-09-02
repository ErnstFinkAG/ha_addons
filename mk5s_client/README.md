# MK5S Client (confirmed-good)

Polls MK5S controller via `/cgi-bin/mkv.cgi` using a fixed QUESTION string and
publishes **confirmed-good** values as Home Assistant sensors:

- `sensor.mk5s_pressure_bar` — 3002/01 HiU16 / 1000
- `sensor.mk5s_motorstarts` — 3007/03 LoU16
- `sensor.mk5s_lastspiele`  — 3007/04 LoU16
- `sensor.mk5s_luefterstarts` — 3007/0B UInt32

## Options

- `host` (string): Controller IP (default `10.60.23.11`)
- `interval` (seconds): Polling interval (default `10`)
- `timeout` (seconds): HTTP timeout (default `5`)
- `verbose` (bool): Log QUESTION + ANSWER and parsed values (default `true`)

