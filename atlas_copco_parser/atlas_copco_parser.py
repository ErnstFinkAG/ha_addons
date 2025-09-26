#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atlas Copco parser/poller
- Strict ordered polling: device1->map1, device2->map1, device1->map2, device2->map2, ...
- No buffering: publish right after each read/decode
- VSD% computed once per cycle using *that device's* running_seconds
- Scaling: temp (/10), pressure (/1000), hours (/3600)
- Service A/B/D counters are u32 seconds => hours (total_increasing)

This is a focused drop-in that preserves your existing topics/metrics parity
but fixes ordering and the VSD math/duplication issues you reported.
"""

import os
import time
import logging

# ---------------- Logging -----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
log = logging.getLogger("atlas_copco")

# ---------------- Mockable IO layer -----------------
class DeviceClient:
    """
    Replace the following stubs with your real HTTP/Modbus calls.
    get_pairs(device, map_id) should return dict like {"3007.01": b'\x00\x00...', ...}
    """
    def get_pairs(self, device, map_id):
        raise NotImplementedError

class MqttClient:
    def publish(self, topic, payload, retain=False):
        # Hook up to your real MQTT client
        print(f"MQTT PUBLISH {topic} {payload} retain={retain}")


# ---------------- Decoders -----------------
def _u16_be(data):  # 2 bytes
    if data is None or len(data) < 2: return None
    return (data[0] << 8) | data[1]

def _u32_be(data):  # 4 bytes
    if data is None or len(data) < 4: return None
    return (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]

def _scale(value, factor):
    if value is None: return None
    return value / factor

# ---------------- Parser config -----------------
DEFAULT_CYCLE_SECONDS = float(os.getenv("AC_CYCLE_SECONDS", "10"))  # do one full pass every N seconds
VSD_KEYS = ("vsd_1_20", "vsd_20_40", "vsd_40_60", "vsd_60_80", "vsd_80_100")


# Map your pairs to logical keys here (example; extend to match your setup)
PAIR_MAP = {
    # pair_id: (key, decoder, scale)
    "3002.26": ("ambient_air", _u16_be, 10),        # temp /10
    "3002.27": ("relative_humidity", _u16_be, 1),
    "3007.01": ("running_hours_seconds", _u32_be, 1),  # raw seconds (not /3600 here)
    "3007.04": ("load_relay", _u32_be, 1),
    "3007.05": ("vsd_1_20_seconds", _u32_be, 1),    # bucket raw seconds
    "3007.06": ("vsd_20_40_seconds", _u32_be, 1),
    "3007.07": ("vsd_40_60_seconds", _u32_be, 1),
    "3007.08": ("vsd_60_80_seconds", _u32_be, 1),
    "3007.09": ("vsd_80_100_seconds", _u32_be, 1),
    "3113.50": ("service_a_1_hours", _u32_be, 3600),
    "3113.51": ("service_a_2_hours", _u32_be, 3600),
    "3113.52": ("service_b_1_hours", _u32_be, 3600),
    "3113.53": ("service_b_2_hours", _u32_be, 3600),
    "3113.54": ("service_d_1_hours", _u32_be, 3600),
    "3113.55": ("service_d_2_hours", _u32_be, 3600),
}

# Which pairs belong to which map, in order
MAPS = [
    # map 1
    ["3007.01", "3007.04", "3007.05", "3007.06", "3007.07", "3007.08", "3007.09"],
    # map 2
    ["3002.26", "3002.27", "3113.50", "3113.51", "3113.52", "3113.53", "3113.54", "3113.55"],
]

# ---------------- Poller -----------------
class Poller:
    def __init__(self, devices, client: DeviceClient, mqtt: MqttClient, base_topic="atlas", cycle_seconds=DEFAULT_CYCLE_SECONDS):
        self.devices = devices  # list of device dicts {name, host, ...}
        self.client = client
        self.mqtt = mqtt
        self.base_topic = base_topic.rstrip("/")
        self.cycle_seconds = float(cycle_seconds)
        # per-device scratch state
        self.state = {
            d["name"]: {
                "running_seconds": None,
                "last_vsd_publish_cycle": -1,
                "vsd_buckets": {},
            } for d in devices
        }
        self.cycle = 0

    def _topic(self, device_name, key):
        return f"{self.base_topic}/{device_name}/{key}"

    def _publish(self, device_name, key, value):
        payload = "null" if value is None else (f"{value:.2f}" if isinstance(value, float) else str(value))
        logging.getLogger(device_name).info(f"{key} = {payload if payload!='null' else 'null'}")
        self.mqtt.publish(self._topic(device_name, key), payload, retain=True)

    def _decode_and_publish(self, device, pair_id, raw):
        name = device["name"]
        if pair_id not in PAIR_MAP:
            return

        key, decoder, scale = PAIR_MAP[pair_id]
        val = decoder(raw)
        if scale != 1 and val is not None:
            val = val / scale

        # capture running_seconds for this device
        if key == "running_hours_seconds":
            self.state[name]["running_seconds"] = val
            # also publish human hours
            self._publish(name, "running_hours", (val / 3600.0) if val is not None else None)
            return

        # service counters already scaled to hours and should be total_increasing
        if key.endswith("_hours"):
            self._publish(name, key.replace("_hours", ""), val)  # publish as 'service_a_1' etc. in hours
            return

        # track VSD buckets in seconds in state
        if key.endswith("_seconds"):
            label = key.replace("_seconds", "").lower()  # vsd_1_20
            self.state[name]["vsd_buckets"][label] = float(val) if val is not None else None

        # standard metrics
        self._publish(name, key, val)

    def _publish_vsd_percentages(self, device):
        """Publish VSD percentages exactly once per cycle per device, based on seconds buckets and that device's running_seconds."""
        name = device["name"]
        if self.state[name]["last_vsd_publish_cycle"] == self.cycle:
            return  # already done this cycle

        running_secs = self.state[name]["running_seconds"]
        if not running_secs or running_secs <= 0:
            return  # cannot compute

        buckets = self.state[name]["vsd_buckets"]
        if not buckets:
            return

        total = float(running_secs)
        for label in VSD_KEYS:
            secs = buckets.get(label, None)
            pct = None
            if secs is not None and total > 0:
                pct = round((secs / total) * 100.0, 2)
                # clamp
                if pct < 0: pct = 0.0
                if pct > 100: pct = 100.0
            self._publish(name, label, pct)

        self.state[name]["last_vsd_publish_cycle"] = self.cycle

    def run_once(self):
        self.cycle += 1
        start = time.monotonic()

        # strict order: map 1 for device1, then map1 for device2, then map2 for device1, etc.
        for map_index, pairs in enumerate(MAPS):
            for device in self.devices:
                name = device["name"]
                try:
                    raw_pairs = self.client.get_pairs(device, map_index + 1)  # 1-based map id
                except Exception as e:
                    log.warning("device %s map %s fetch failed: %s", name, map_index + 1, e)
                    continue

                # publish immediately pair-by-pair in the order declared in MAPS
                for pair_id in pairs:
                    raw = raw_pairs.get(pair_id)
                    self._decode_and_publish(device, pair_id, raw)

                # After finishing the map that contains VSD buckets and running_seconds,
                # publish VSD% once per cycle.
                if any(pid in pairs for pid in ("3007.01","3007.05","3007.06","3007.07","3007.08","3007.09")):
                    self._publish_vsd_percentages(device)

        # sleep remaining to honor cycle length
        elapsed = time.monotonic() - start
        remaining = self.cycle_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    # Example wiring: replace with your real devices and clients
    devices = [
        {"name": "eftool-bw-b2-f3-air11", "host": "10.60.23.11"},
        {"name": "eftool-bw-b2-f3-air12", "host": "10.60.23.12"},
    ]
    client = DeviceClient()  # replace with your concrete implementation
    mqtt = MqttClient()
    poller = Poller(devices, client, mqtt, base_topic="atlas", cycle_seconds=DEFAULT_CYCLE_SECONDS)
    # Run one cycle in this demo
    # poller.run_once()
    pass
