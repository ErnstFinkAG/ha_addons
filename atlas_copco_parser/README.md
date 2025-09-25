
# Atlas Copco Parser (0.0.9)

Single-file parser with detailed logging and MQTT publishing.

## Features
- Sequential polling only (prevents value/key mixups).
- Very verbose per-metric logs: model, key, pair, question, part/decoder, bytes, raw, calc, value, unit, topic.
- Correct maps for **GA15VS23A** and **GA15VP13**.
- Legacy env fallback (works without YAML):
  - `AC_HOSTS`, `AC_MODELS`, optional `AC_NAMES`
  - `TIMEOUT`, `VERBOSE`
- MQTT envs: `MQTT_HOST`/`MQTT_PORT`/`MQTT_USER`/`MQTT_PASSWORD`.
- Bump: version 0.0.9.

## Quick Start (Legacy Env Mode)
```
AC_HOSTS=10.60.23.11,10.60.23.12
AC_MODELS=GA15VP13,GA15VS23A
AC_NAMES=eftool-bw-b2-f3-air11,eftool-bw-b2-f3-air12
MQTT_HOST=broker
MQTT_PORT=1883
VERBOSE=true
TIMEOUT=2.5
python3 atlas_copco_parser.py
```

## Config File (optional)
Place `/config/config.yml` or set `AC_CONFIG=/path/to/config.yml`:

```yaml
mqtt:
  host: broker
  port: 1883
  user: ""
  password: ""

base_prefix: atlas_copco
discovery_prefix: homeassistant

devices:
  - name: eftool-bw-b2-f3-air11
    ip: 10.60.23.11
    model: GA15VP13
    timeout: 2.5
    verbose: true

  - name: eftool-bw-b2-f3-air12
    ip: 10.60.23.12
    model: GA15VS23A
    timeout: 2.5
    verbose: true
```

## Notes
- The HTTP endpoints differ across controllers. This script tries a few common paths:
  `/{question}`, `/q?code={question}`, `/values?obj={question}`.
- If your controller requires a different path or authentication, adapt `DeviceSession.ask_question` accordingly.
- Set `ONE_SHOT=true` to run a single poll cycle, else it loops with `POLL_INTERVAL` (seconds).

## License
MIT
