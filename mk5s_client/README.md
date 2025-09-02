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
