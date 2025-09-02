# MK5S Client (confirmed-good)

Polls MK5S `/cgi-bin/mkv.cgi` with a fixed QUESTION string, logs the raw QUESTION/ANSWER,
and decodes confirmed-good values:

- Pressure (bar) from 3002/01 (HiU16 / 1000)
- Motorstarts from 3007/03 (LoU16)
- Lastspiele from 3007/04 (LoU16)
- Lüfterstarts from 3007/0B (UInt32)

## Options
- `host` (default `10.60.23.11`)
- `interval` seconds (default `10`)
- `timeout` seconds (default `5`)
- `verbose` (default `true`) — logs QUESTION/ANSWER

