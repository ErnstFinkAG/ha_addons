#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atlas Copco Parser – version 0.0.7
- Sequential polling (no parallel threads) as requested
- Detailed per-value logging showing:
  model, question_var, key, pair, question, encoding (part/decoder),
  bytes (hex), raw (int), calculation string, resulting value with unit,
  and MQTT topic.
- Uses explicit per-model sensor maps (GA15VS23A and GA15VP13 provided).
- Publishes to MQTT with topic atlas_copco/<slug(name)>/sensor/<slug(key)>
- Fixes indentation issues in setup section (auto, bus)
"""

import os
import sys
import time
import json
import signal
import logging
import socket
from typing import Dict, Any, Optional, Tuple, List

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # In some environments, only the structure is needed

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover
    mqtt = None

VERSION = "0.0.7"

# ---------------- Sensor maps ----------------
SENSORS_GA15VS23A: Dict[str, Dict[str, Any]] = {
    "machine_status":         {"pair":"3001.08","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"measurement","name":"Machine Status"},
    "controller_temperature": {"pair":"3002.01","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Controller Temperature"},
    "compressor_outlet":      {"pair":"3002.24","part":"hi","decode":"_div1000","unit":"bar","device_class":"pressure","state_class":"measurement","name":"Compressor Outlet"},
    "ambient_air":            {"pair":"3002.26","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Ambient Air"},
    "relative_humidity":      {"pair":"3002.27","part":"hi","decode":"_id","unit":"%","device_class":"humidity","state_class":"measurement","name":"Relative Humidity"},
    "element_outlet":         {"pair":"3002.2A","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Element Outlet"},
    "aftercooler_pcb_temp":   {"pair":"3002.66","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Aftercooler Drain PCB Temperature"},
    "running_hours":          {"pair":"3007.01","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Running Hours"},
    "motor_starts":           {"pair":"3007.03","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Motor Starts"},
    "load_relay":             {"pair":"3007.04","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Load Relay"},
    "vsd_1_20":               {"pair":"3007.05","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 1–20%"},
    "vsd_20_40":              {"pair":"3007.06","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 20–40%"},
    "vsd_40_60":              {"pair":"3007.07","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 40–60%"},
    "vsd_60_80":              {"pair":"3007.08","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 60–80%"},
    "vsd_80_100":             {"pair":"3007.09","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 80–100%"},
    "fan_starts":             {"pair":"3007.0B","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Fan Starts"},
    "accumulated_volume":     {"pair":"3007.0C","part":"u32","decode":"_times1000","unit":"m³","device_class":None,"state_class":"total_increasing","name":"Accumulated Volume"},
    "module_hours":           {"pair":"3007.0D","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Module Hours"},
    "emergency_stops":        {"pair":"3007.0E","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Emergency Stops"},
    "direct_stops":           {"pair":"3007.0F","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Direct Stops"},
    "recirculation_starts":   {"pair":"3007.17","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Starts"},
    "recirculation_failures": {"pair":"3007.18","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Failures"},
    "low_load_hours":         {"pair":"3007.1B","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Low Load Hours"},
    "available_hours":        {"pair":"3007.25","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Available Hours"},
    "unavailable_hours":      {"pair":"3007.26","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Unavailable Hours"},
    "emergency_stop_hours":   {"pair":"3007.27","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Emergency Stop Hours"},
    "display_hours":          {"pair":"3007.43","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Display Hours"},
    "boostflow_hours":        {"pair":"3007.4C","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Boostflow Hours"},
    "boostflow_activations":  {"pair":"3007.4D","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Boostflow Activations"},
    "emergency_stops_running":{"pair":"3007.54","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Emergency Stops During Running"},
    "drain1_op_time":         {"pair":"3007.55","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Drain 1 Operation Time"},
    "drain1_switching":       {"pair":"3007.56","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Drain 1 Switching Actions"},
    "drain1_manual":          {"pair":"3007.57","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Drain 1 Manual Drainings"},
    "motor_rpm_requested":    {"pair":"3021.01","part":"lo","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Motor Requested RPM"},
    "motor_rpm_actual":       {"pair":"3021.01","part":"hi","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Motor Actual RPM"},
    "flow":                   {"pair":"3021.05","part":"u32","decode":"_id","unit":"%","device_class":None,"state_class":"measurement","name":"Flow"},
    "motor_amperage":         {"pair":"3021.0A","part":"hi","decode":"_id","unit":"A","device_class":"current","state_class":"measurement","name":"Motor Amperage"},
    "fan_rpm_requested":      {"pair":"3022.01","part":"lo","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Fan Motor Requested RPM"},
    "fan_rpm_actual":         {"pair":"3022.01","part":"hi","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"Fan Motor Actual RPM"},
    "fan_motor_amperage":     {"pair":"3022.0A","part":"hi","decode":"_id","unit":"A","device_class":"current","state_class":"measurement","name":"Fan Motor Amperage"},
    "service_a_1":            {"pair":"3113.50","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 1"},
    "service_a_2":            {"pair":"3113.51","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 2"},
    "service_b_1":            {"pair":"3113.52","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 1"},
    "service_b_2":            {"pair":"3113.53","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 2"},
    "service_d_1":            {"pair":"3113.54","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service D 1"},
    "service_d_2":            {"pair":"3113.55","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service D 2"},
}

SENSORS_GA15VP13: Dict[str, Dict[str, Any]] = {
    "machine_status":         {"pair":"3001.08","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"measurement","name":"Machine Status"},
    "compressor_outlet":      {"pair":"3002.01","part":"hi","decode":"_div1000","unit":"bar","device_class":"pressure","state_class":"measurement","name":"Compressor Outlet"},
    "element_outlet":         {"pair":"3002.03","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Element Outlet"},
    "ambient_air":            {"pair":"3002.05","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Ambient Air"},
    "controller_temperature": {"pair":"3002.08","part":"hi","decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Controller Temperature"},
    "running_hours":          {"pair":"3007.01","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Running Hours"},
    "motor_starts":           {"pair":"3007.03","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Motor Starts"},
    "load_cycles":            {"pair":"3007.04","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Load Cycles"},
    "vsd_1_20":               {"pair":"3007.05","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 1–20%"},
    "vsd_20_40":              {"pair":"3007.06","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 20–40%"},
    "vsd_40_60":              {"pair":"3007.07","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 40–60%"},
    "vsd_60_80":              {"pair":"3007.08","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 60–80%"},
    "vssd_80_100":            {"pair":"3007.09","part":"u32","decode":"_percent_from_bucket","unit":"%","device_class":None,"state_class":"measurement","name":"VSD 80–100%"},
    "fan_starts":             {"pair":"3007.0B","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Fan Starts"},
    "accumulated_volume":     {"pair":"3007.0C","part":"u32","decode":"_times1000","unit":"m³","device_class":None,"state_class":"total_increasing","name":"Accumulated Volume"},
    "module_hours":           {"pair":"3007.0D","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Module Hours"},
    "emergency_stops":        {"pair":"3007.0E","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Emergency Stops"},
    "direct_stops":           {"pair":"3007.0F","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Direct Stops"},
    "recirculation_starts":   {"pair":"3007.14","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Starts"},
    "recirculation_failures": {"pair":"3007.15","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Failures"},
    "low_load_hours":         {"pair":"3007.18","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Low Load Hours"},
    "available_hours":        {"pair":"3007.22","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Available Hours"},
    "unavailable_hours":      {"pair":"3007.23","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Unavailable Hours"},
    "emergency_stop_hours":   {"pair":"3007.24","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Emergency Stop Hours"},
    "rpm_requested":          {"pair":"3021.01","part":"lo","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"RPM Requested"},
    "rpm_actual":             {"pair":"3021.01","part":"hi","decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"RPM Actual"},
    "motor_amperage":         {"pair":"3021.05","part":"hi","decode":"_id","unit":"A","device_class":"current","state_class":"measurement","name":"Motor Amperage"},
    "flow":                   {"pair":"3021.0A","part":"u32","decode":"_id","unit":"%","device_class":None,"state_class":"measurement","name":"Flow"},
    "service_a_1":            {"pair":"3113.50","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 1"},
    "service_a_2":            {"pair":"3113.51","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service A 2"},
    "service_b_1":            {"pair":"3113.52","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 1"},
    "service_b_2":            {"pair":"3113.53","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Service B 2"},
}

MODEL_MAPS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "GA15VS23A": SENSORS_GA15VS23A,
    "GA15VP13": SENSORS_GA15VP13,
}

# ---------------- Utilities ----------------
def slugify(s: str) -> str:
    out = []
    prev_us = False
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        else:
            if not prev_us:
                out.append("_")
            prev_us = True
    res = "".join(out).strip("_")
    while "__" in res:
        res = res.replace("__", "_")
    return res


def hex_or_none(b: Optional[bytes]) -> Optional[str]:
    if b is None:
        return None
    return b.hex()


def decode_raw_from_part(b: Optional[bytes], part: str) -> Optional[int]:
    if b is None:
        return None
    try:
        if part == "u32":
            if len(b) >= 4:
                return int.from_bytes(b[0:4], "big", signed=False)
            return int.from_bytes(b, "big", signed=False)
        elif part == "hi":
            if len(b) >= 2:
                return int.from_bytes(b[0:2], "big", signed=False)
            return int.from_bytes(b, "big", signed=False)
        elif part == "lo":
            if len(b) >= 4:
                return int.from_bytes(b[2:4], "big", signed=False)
            elif len(b) >= 2:
                return int.from_bytes(b[-2:], "big", signed=False)
            return int.from_bytes(b, "big", signed=False)
        else:
            # default treat as u32
            return int.from_bytes(b, "big", signed=False)
    except Exception:
        return None


def hours_from_seconds_u32(raw: Optional[int]) -> Optional[float]:
    return None if raw is None else (raw / 3600.0)


def percent_from_buckets(v: Optional[int], totals: Optional[int]) -> Optional[float]:
    if v is None or not totals or totals <= 0:
        return None
    # two decimal places to match expected formatting
    return round((v * 100.0) / float(totals), 2)


def apply_decode(decode: str, raw: Optional[int], ctx: Dict[str, Any]) -> Tuple[Optional[float], str]:
    """
    Returns (value, calc_str)
    """
    if decode == "_id":
        return (None if raw is None else float(raw) if isinstance(raw, (int, float)) else None,
                "value = _id(raw)")
    if decode == "_div10":
        return (None if raw is None else raw / 10.0, "value = raw/10.0")
    if decode == "_div1000":
        return (None if raw is None else raw / 1000.0, "value = raw/1000.0")
    if decode == "_times1000":
        return (None if raw is None else raw * 1000.0, "value = _times1000(raw)")
    if decode == "_hours_from_seconds_u32":
        return (hours_from_seconds_u32(raw), "value = raw/3600.0")
    if decode == "_percent_from_bucket":
        total = ctx.get("vsd_total_raw")
        return (percent_from_buckets(raw, total), "value = percent_from_bucket(raw)")
    # fallback
    return (None if raw is None else float(raw), "value = raw")


class MqttBus:
    def __init__(self, host: str, port: int, user: Optional[str], password: Optional[str], client_id: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.client_id = client_id
        self.client = None

        if mqtt is not None:
            self.client = mqtt.Client(client_id=self.client_id, clean_session=True, protocol=mqtt.MQTTv311)
            if user or password:
                self.client.username_pw_set(user, password)
            self.client.on_connect = self._on_connect
            self.client.connect_async(self.host, self.port, keepalive=30)
            self.client.loop_start()
        else:  # pragma: no cover
            logging.warning("paho-mqtt not available; MQTT publish will be no-ops.")

    def _on_connect(self, _client, _userdata, _flags, rc):
        logging.info("MQTT connected rc=%s", rc)

    def publish(self, topic: str, payload: str, retain: bool = True, qos: int = 0) -> None:
        if self.client is None:  # pragma: no cover
            return
        try:
            self.client.publish(topic, payload=payload, qos=qos, retain=retain)
        except Exception as e:  # pragma: no cover
            logging.warning("MQTT publish failed: %r", e)


def build_question(pair: str) -> str:
    # "3007.01" -> "300701"
    return pair.replace(".", "")


def fetch_pair_bytes(session: Any, ip: str, question: str, timeout: float) -> Optional[bytes]:
    """
    Replace this with the actual protocol for your controllers.
    This default implementation tries a simple HTTP GET against two common patterns.
    """
    if requests is None:
        return None
    templates = [
        os.getenv("ATLAS_ENDPOINT_TEMPLATE") or "http://{ip}/q/{question}",
        "http://{ip}/?q={question}",
    ]
    for tmpl in templates:
        url = tmpl.format(ip=ip, question=question)
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            # Expect raw binary; if hex string, convert
            if r.headers.get("Content-Type", "").lower().startswith("application/octet-stream"):
                return r.content
            text = r.text.strip()
            # If looks like hex: e.g. "0003776a"
            if all(c in "0123456789abcdefABCDEF" for c in text) and len(text) % 2 == 0:
                try:
                    return bytes.fromhex(text)
                except Exception:
                    pass
            # Otherwise, try JSON {"bytes":"0003776a"}
            try:
                data = r.json()
                if isinstance(data, dict) and "bytes" in data and isinstance(data["bytes"], str):
                    return bytes.fromhex(data["bytes"])
            except Exception:
                pass
            # Fallback: None
            return None
        except Exception as e:
            last_exc = e
    # If all attempts failed, bubble last
    raise last_exc  # type: ignore


def read_one(session, ip: str, key: str, spec: Dict[str, Any], ctx: Dict[str, Any], device_name: str, model: str, discovery_prefix: str, base_prefix: str, bus: MqttBus, verbose: int) -> None:
    pair = spec["pair"]
    part = spec["part"]
    decode = spec["decode"]
    unit = spec.get("unit")
    question = build_question(pair)

    b: Optional[bytes] = None
    raw: Optional[int] = None
    exc: Optional[Exception] = None

    try:
        b = fetch_pair_bytes(session, ip, question, timeout=ctx["timeout"])
        raw = decode_raw_from_part(b, part)
    except Exception as e:
        exc = e

    if exc is not None:
        logging.warning("pair %s exc: %r", pair, exc)

    calc_val, calc_str = apply_decode(decode, raw, ctx)

    # Quick unit suffix formatting
    value_str = "null" if calc_val is None else (("%g" % calc_val) if unit is None else ("%g %s" % (calc_val, unit)))
    # hex or None
    hex_bytes = hex_or_none(b)

    slug_dev = slugify(device_name)
    topic = f"{base_prefix}/{slug_dev}/sensor/{slugify(key)}"

    # log line in the requested verbose format
    # Show the variable name for "question string" (question_var = model)
    encoding = f"{part}/{decode}"

    logging.info("[%s] model=%s question_var=%s key=%s pair=%s question=%s encoding=%s bytes=%s raw=%s calc=%s -> value=%s topic=%s",
                 device_name, model, model, key, pair, question, encoding,
                 hex_bytes if hex_bytes is not None else "",
                 "None" if raw is None else str(raw),
                 calc_str, value_str, topic)

    # Publish to MQTT
    payload = "null" if calc_val is None else json.dumps(calc_val)
    bus.publish(topic, payload)

    # for HA discovery you might publish additional config topics; omitted here intentionally


def pick_sensor_map(model: str) -> Dict[str, Dict[str, Any]]:
    return MODEL_MAPS.get(model, {})


RUNNING = True


def handle_sigterm(_signo, _frame):
    global RUNNING
    logging.info("signal 15 received, exiting...")
    RUNNING = False


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info("[atlas_copco_parser] starting...")

    # ----- Options from env (Home Assistant add-on style) -----
    mqtt_host = os.getenv("MQTT_HOST", "localhost")
    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_user = os.getenv("MQTT_USER", "") or None
    mqtt_password = os.getenv("MQTT_PASSWORD", "") or None

    # Device config (CSV aligned by index)
    ips = [s.strip() for s in os.getenv("ATLAS_IPS", "").split(",") if s.strip()]
    names = [s.strip() for s in os.getenv("ATLAS_NAMES", "").split(",") if s.strip()]
    models = [s.strip() for s in os.getenv("ATLAS_MODELS", "").split(",") if s.strip()]

    # align lengths
    n = min(len(ips), len(names), len(models))
    ips, names, models = ips[:n], names[:n], models[:n]

    # Per-device timeouts/intervals
    timeouts = [float(x) if x else 2.0 for x in os.getenv("ATLAS_TIMEOUTS", "").split(",")] if os.getenv("ATLAS_TIMEOUTS") else [2.0] * n
    intervals = [float(x) if x else 10.0 for x in os.getenv("ATLAS_INTERVALS", "").split(",")] if os.getenv("ATLAS_INTERVALS") else [10.0] * n
    verboses = [int(x) if x else 1 for x in os.getenv("ATLAS_VERBOSITY", "").split(",")] if os.getenv("ATLAS_VERBOSITY") else [1] * n

    discovery_prefix = os.getenv("DISCOVERY_PREFIX", "homeassistant")

    # Indentation fixes: keep these left-aligned with discovery_prefix
    auto = bool(str(os.getenv("AUTODETECT", "true")).lower() in ("1","true","yes","on"))
    bus = MqttBus(mqtt_host, mqtt_port, mqtt_user, mqtt_password, client_id=f"atlas_copco_{int(time.time())}")

    sessions = []
    if requests is not None:
        for _ in range(n):
            sessions.append(requests.Session())
    else:
        sessions = [object()] * n  # stubs

    # Force sequential mode as requested
    logging.info("Sequential mode enabled (forced): polling one device at a time.")

    signal.signal(signal.SIGTERM, handle_sigterm)

    # Poll loop
    while RUNNING:
        cycle_start = time.time()
        for i in range(n):
            if not RUNNING:
                break
            ip = ips[i]
            name = names[i]
            model = models[i]
            timeout = timeouts[i] if i < len(timeouts) else 2.0
            interval = intervals[i] if i < len(intervals) else 10.0
            verbose = verboses[i] if i < len(verboses) else 1

            sensor_map = pick_sensor_map(model)
            if not sensor_map:
                logging.warning("[%s] Unknown model '%s' – skipping", name, model)
                continue

            session = sessions[i]

            # First pass: read all bytes/raw into ctx
            ctx: Dict[str, Any] = {"timeout": timeout}
            per_key_bytes: Dict[str, Optional[bytes]] = {}
            per_key_raw: Dict[str, Optional[int]] = {}

            # Try to prefetch VSD buckets to compute percentages with a proper denominator
            vsd_keys = [k for k in sensor_map.keys() if k.startswith("vsd_")]
            # Read everything (sequentially)
            for key, spec in sensor_map.items():
                pair = spec["pair"]
                part = spec["part"]
                question = build_question(pair)
                try:
                    b = fetch_pair_bytes(session, ip, question, timeout=timeout)
                    raw = decode_raw_from_part(b, part)
                    per_key_bytes[key] = b
                    per_key_raw[key] = raw
                except Exception as e:
                    per_key_bytes[key] = None
                    per_key_raw[key] = None
                    logging.warning("pair %s exc: %r", pair, e)

            # Compute denominator for vsd percentages
            vsd_total_raw = sum((per_key_raw.get(k) or 0) for k in vsd_keys) if vsd_keys else None
            if vsd_total_raw == 0:
                vsd_total_raw = None
            ctx["vsd_total_raw"] = vsd_total_raw

            # Second pass: compute values, log, publish
            base_prefix = "atlas_copco"
            for key, spec in sensor_map.items():
                # Reuse fetched bytes/raw to avoid second device hit
                b = per_key_bytes.get(key)
                raw = per_key_raw.get(key)
                # Temporarily override fetch in context passing
                # Compose calc/encoding
                part = spec["part"]
                decode = spec["decode"]
                unit = spec.get("unit")

                calc_val, calc_str = apply_decode(decode, raw, ctx)

                value_str = "null" if calc_val is None else (("%g" % calc_val) if unit is None else ("%g %s" % (calc_val, unit)))
                hex_bytes = hex_or_none(b)
                pair = spec["pair"]
                question = build_question(pair)
                encoding = f"{part}/{decode}"
                slug_dev = slugify(name)
                topic = f"{base_prefix}/{slug_dev}/sensor/{slugify(key)}"
                logging.info("[%s] model=%s question_var=%s key=%s pair=%s question=%s encoding=%s bytes=%s raw=%s calc=%s -> value=%s topic=%s",
                             name, model, model, key, pair, question, encoding,
                             hex_bytes if hex_bytes is not None else "",
                             "None" if raw is None else str(raw),
                             calc_str, value_str, topic)
                payload = "null" if calc_val is None else json.dumps(calc_val)
                bus.publish(topic, payload)

            # Respect per-device interval (simple pacing)
            if RUNNING:
                time.sleep(interval)

        # Minimal guard to avoid tight loop if no devices
        if n == 0:
            time.sleep(5.0)

    # graceful shutdown
    time.sleep(0.1)
    logging.info("shutdown complete.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        handle_sigterm(None, None)
