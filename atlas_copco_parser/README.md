# Atlas Copco Parser — Home Assistant Add-on

Polls Atlas Copco MK5s Touch controllers over HTTP and publishes sensors to MQTT with Home Assistant Discovery.

## Options (CSV lists)
- `ip_list`: Comma-separated IPs (e.g. `"10.0.0.10,10.0.0.11"`)
- `name_list`: Comma-separated names (same length as `ip_list`)
- `interval_list`: Comma-separated polling intervals in seconds (defaults to `10` per host)
- `timeout_list`: Comma-separated HTTP timeouts in seconds (default `5` per host)
- `verbose_list`: Comma-separated booleans (e.g. `true,false`) for per-host debug logging
- `question`: Optional controller family key if all devices are identical: `GA15VS23A` or `GA15VP13`
- `question_list`: Optional per-host question list (overrides `question`)
- `mqtt_*`: Connection settings for your MQTT broker
- `discovery_prefix`: Home Assistant discovery prefix (default `homeassistant`)

## Notes
* This build uses individual pair reads (slower but robust) and will attempt bulk queries if a response format match is detected.
* Topics look like:
  - `atlas_copco/<device>/availability`
  - `atlas_copco/<device>/sensor/<sensor_key>`
  - Discovery under: `<discovery_prefix>/sensor/atlas_copco_<device>/<sensor_key>/config`
