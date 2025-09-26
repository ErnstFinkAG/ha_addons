# Atlas Copco Parser Update (Ordered fetch + single-cycle VSD)

Key points:
- **Strict order**: map-by-map across devices, publishing per pair immediately.
- **VSD %**: computed once per cycle, using the same device's `running_hours_seconds` and the bucket seconds.
- **Scaling**: temp (/10), pressure (/1000) when wired, hours (/3600).
- **Service counters**: A/B/D u32 seconds → hours (total_increasing friendly).
- **Cycle control**: set `AC_CYCLE_SECONDS` env var (default 10).

Integrate:
1. Drop `atlas_copco_parser.py` over your current one.
2. Wire `DeviceClient.get_pairs(device, map_id)` to your actual transport to return raw bytes for the pairs listed in `MAPS`.
3. Replace `MqttClient.publish` with your live MQTT client if needed.
