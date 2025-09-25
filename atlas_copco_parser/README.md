# Atlas Copco Parser (v0.0.7)

- Sequential polling only (no parallelism), as requested.
- Extremely verbose logging per line: model, question_var (the variable name), key, pair (e.g. 3007.01), question (e.g. 300701), encoding (part/decoder), bytes (hex), raw, calculation formula, computed value + unit, and MQTT topic.
- Uses the exact sensor maps you provided for **GA15VS23A** and **GA15VP13**.
- Fixes indentation around `autodetect` and `bus` initialisation.
- MQTT topics: `atlas_copco/<slug(device_name)>/sensor/<slug(key)>` (same slugging you saw: hyphens → underscores).

## Environment variables

```
MQTT_HOST=...
MQTT_PORT=1883
MQTT_USER=...
MQTT_PASSWORD=...

ATLAS_IPS=10.60.23.11,10.60.23.12
ATLAS_NAMES=eftool-bw-b2-f3-air11,eftool-bw-b2-f3-air12
ATLAS_MODELS=GA15VP13,GA15VS23A

# Optional
ATLAS_TIMEOUTS=2,2
ATLAS_INTERVALS=10,10
ATLAS_VERBOSITY=1,1
DISCOVERY_PREFIX=homeassistant
AUTODETECT=true

# If you need a custom HTTP endpoint format for reading registers:
ATLAS_ENDPOINT_TEMPLATE="http://{ip}/?q={question}"
```

> **Note**: `fetch_pair_bytes` is a minimal HTTP reader. If your controllers use a different protocol, plug in your existing code there. The rest (maps, decoding, logging, MQTT) is wired and ready.

## Run

```
python3 atlas_copco_parser.py
```

Stop with SIGTERM / Ctrl+C – you'll see `signal 15 received, exiting...` then `shutdown complete.`

