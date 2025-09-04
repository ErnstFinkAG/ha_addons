# MK5S Client

A minimal Home Assistant add-on that polls an MK5S controller and logs confirmed-good values:
- Kompressorauslass (pressure, bar)
- Motorstarts
- Lastspiele

## Options
- `host` (string) IP or host of controller (default `10.60.23.11`)
- `interval` (int) seconds between polls
- `timeout` (int) HTTP timeout seconds
- `verbose` (bool) log question/answer and response headers

## Build/runtime notes
- Uses system `py3-requests` (no pip needed) to avoid PEP 668 issues.


## Now included sensors (confirmed-good)
- Kompressorauslass (bar) — 3002.01 (HiU16/1000)
- Elementauslass (°C) — 3002.03 (HiU16/10)
- Umgebungsluft (°C) — 3002.05 (HiU16/10)
- Controller Temperature (°C) — 3002.08 (HiU16/10)
- Motorstarts — 3007.03 (LoU16)
- Lastspiele — 3007.04 (LoU16)
- Lüfterstarts — 3007.0B (UInt32)
- Erzeugte Druckluftmenge (m³) — 3007.0C (LoU16 * 1000)
