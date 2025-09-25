# Atlas Copco Parser (updated)

Version: 0.0.7

- Sequential polling only (no parallel).
- Extremely verbose per-signal log line includes:
  `model, question_var, key, pair, question, encoding, bytes, raw, calc, unit, topic`
- Fixed/configurable MQTT client_id to avoid rc=5 when broker ACLs expect a stable identifier.
- Sensor maps for `GA15VS23A` and `GA15VP13` (as provided).
- HTTP question URL is **configurable** via `question_templates` so you can match your device API without code changes.

## Config

Create `/config/config.yml` (or set `ACPARSER_CONFIG` env) like:

```yaml
mqtt:
  host: 127.0.0.1
  port: 1883
  user: myuser
  password: mypass
  client_id: atlas_copco_parser
  tls: false

discovery_prefix: homeassistant

# List of templates tried in order. Must contain {ip} and {question}
question_templates:
  - "http://{ip}/q?m={question}"
  - "http://{ip}/mem/{question}"
  - "http://{ip}/api/mb?m={question}"

devices:
  - name: eftool-bw-b2-f3-air11
    ip: 10.60.23.11
    device_type: GA15VP13
  - name: eftool-bw-b2-f3-air12
    ip: 10.60.23.12
    device_type: GA15VS23A
```

Or provide environment variable for devices:
```
ACPARSER_DEVICES="eftool-bw-b2-f3-air11,10.60.23.11,GA15VP13;eftool-bw-b2-f3-air12,10.60.23.12,GA15VS23A"
```

## MQTT

- Topics: `atlas_copco/<slug(name)>/sensor/<key>`
- Payload: JSON number or `null`

## Notes

- If you see `MQTT connected rc=5 (Not authorized)`, either credentials/ACLs are wrong **or** your broker rejects changing client IDs. Set a fixed `mqtt.client_id` or `MQTT_CLIENT_ID` env.
- If fetch fails, adjust `question_templates` to the correct device endpoint that returns 4 bytes per question.
