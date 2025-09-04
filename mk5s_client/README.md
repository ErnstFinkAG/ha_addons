# MK5S Client (Home Assistant add-on)

Polls an Atlas Copco **MK5S Touch** air compressor controller and publishes
confirmed-good metrics to **MQTT**, including **Home Assistant MQTT Discovery**
entities.

> **Confirmed-good sensors**
>
> - `Kompressorauslass` — discharge pressure (bar) from `3002.01` (`HiU16/1000`)
> - `Elementauslass` — element outlet temp (°C) from `3002.03` (`HiU16/10`)
> - `Umgebungsluft` — ambient temp (°C) from `3002.05` (`HiU16/10`)
> - `Controller Temperature` (°C) from `3002.08` (`HiU16/10`)
> - `Motorstarts` — starts counter from `3007.03` (`LoU16`)
> - `Lastspiele` — load cycles counter from `3007.04` (`LoU16`)
> - `Lüfterstarts` — fan starts from `3007.0B` (`LoU16`)
> - `Erzeugte Druckluftmenge` — produced air volume (m³) from `3007.0C` (`LoU16 * 1000`)

The add-on **does not** change controller settings; it only reads.

## Configuration (CSV per-host)

All list-like options support comma-separated values.
If a list has a single value, it is applied to all hosts.

```yaml
hosts: "10.60.23.11,10.60.23.12"
names: "mk5s_a,mk5s_b"              # Used in MQTT topics and unique_ids
intervals: "10,15"                  # seconds per host
timeouts: "5,5"                     # seconds per request
verbose: "false,true"               # per host debug logging
questions: ""                       # optional per host; hex string, 6-hex/key
mqtt_host: "localhost"
mqtt_port: 1883
mqtt_user: "mqtt_user"
mqtt_password: "your_password"
discovery_prefix: "homeassistant"
```

> **Default Question (used when `questions` is empty)**  
> `30020130020330020530020830070130070330070430070B30070C`  
> (Only the confirmed-good keys; you may paste your larger question if desired.)

## MQTT

- State topics: `mk5s/<name>/<key>/state` (e.g. `mk5s/mk5s/3002.01/state`)
- Discovery: `homeassistant/sensor/<name>_<key>/config`
- Device: `manufacturer=Atlas Copco`, `model=MK5S Touch`, identifier `mk5s_<name>`

## Notes

- The controller endpoint used is `http://<host>/cgi-bin/mkv.cgi` via POST.
- The request body is the raw hex question string (fallback form-encoded on error).
- Each 6-hex chunk in the question denotes a key: `IIII SS` → `IIII.SS` (e.g. `3002.01`).
- The answer is parsed in 8-hex words (one per key), big-endian `UInt32` → `HiU16/LoU16`.

## Troubleshooting

- If you see `INCORRECT PATH` in the logs: the device rejected the endpoint/body.
  The client auto-retries with a form-encoded body. Verify network reachability.
- Use `verbose=true` for a host to log raw question/answer and HTTP headers.
