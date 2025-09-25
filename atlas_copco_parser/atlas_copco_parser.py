#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Atlas Copco parser with:
- Sequential polling (no parallel)
- Very verbose per-signal logging (pair, question var name, question string, encoding, bytes, raw, calc, unit, topic)
- Fixed or configurable MQTT client_id to avoid rc=5 "Not authorized"
- Sensor maps for GA15VS23A and GA15VP13 (as provided)
- Pluggable HTTP question templates to fetch 4-byte values from device (best-effort; make sure to set correct template in config)
- Home Assistant discovery prefix preserved (configurable)
"""

import os
import sys
import time
import json
import logging
import threading
import signal
from typing import Any, Dict, Optional, Tuple, List

import requests
from requests import Session
import paho.mqtt.client as mqtt
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

APP_NAME = "atlas_copco_parser"
VERSION = "0.0.7"

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(APP_NAME)

# ---------------- Helpers ----------------
def slugify(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", ".", "/", "\\"):
            out.append("_")
        else:
            out.append("_")
    return "".join(out).strip("_")

def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1","true","yes","on")

def read_yaml_config(path: str) -> Dict[str, Any]:
    if not yaml:
        return {}
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# ---------------- Decoders ----------------
def _id(x: Optional[int]) -> Optional[int]:
    return None if x is None else int(x)

def _div10(x: Optional[int]) -> Optional[float]:
    return None if x is None else x / 10.0

def _div1000(x: Optional[int]) -> Optional[float]:
    return None if x is None else x / 1000.0

def _times1000(x: Optional[int]) -> Optional[int]:
    return None if x is None else x * 1000

def _hours_from_seconds_u32(x: Optional[int]) -> Optional[float]:
    return None if x is None else x / 3600.0

def percent_from_bucket(x: Optional[int]) -> Optional[float]:
    # Observed mapping: raw seems to be millis of total 65535*1000
    if x is None:
        return None
    denom = 65535.0 * 1000.0
    return (x / denom) * 100.0

DECODERS = {
    "_id": _id,
    "_div10": _div10,
    "_div1000": _div1000,
    "_times1000": _times1000,
    "_hours_from_seconds_u32": _hours_from_seconds_u32,
    "_percent_from_bucket": percent_from_bucket,
}

# ---------------- Sensor maps (provided) ----------------
from typing import Dict as _Dict
SENSORS_GA15VS23A: _Dict[str, _Dict[str, Any]] = {
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
}

SENSORS_GA15VP13: _Dict[str, _Dict[str, Any]] = {
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

MODEL_MAP: Dict[str, Dict[str, Any]] = {
    "GA15VS23A": SENSORS_GA15VS23A,
    "GA15VP13": SENSORS_GA15VP13,
}

# ---------------- MQTT Bus ----------------
class MqttBus:
    def __init__(self, host: str, port: int, username: Optional[str], password: Optional[str], client_id: str, tls: bool=False):
        self.client = mqtt.Client(client_id=client_id, clean_session=True)
        if username:
            self.client.username_pw_set(username, password or None)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        if tls:
            self.client.tls_set()
        self.host = host
        self.port = port
        self._connected = threading.Event()
        self.client.loop_start()

    def on_connect(self, client, userdata, flags, rc):
        RC_TEXT = {
            0: "Connection accepted",
            1: "Unacceptable protocol version",
            2: "Identifier (client_id) rejected",
            3: "Server unavailable",
            4: "Bad username or password",
            5: "Not authorized (check ACLs / client_id / TLS policy)"
        }
        fn = log.info if rc == 0 else log.error
        fn("MQTT connected rc=%s (%s)", rc, RC_TEXT.get(rc, "Unknown"))
        if rc == 0:
            self._connected.set()

    def on_disconnect(self, client, userdata, rc):
        log.warning("MQTT disconnected rc=%s", rc)
        self._connected.clear()

    def connect(self, timeout: float = 10.0):
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()
        if not self._connected.wait(timeout):
            log.error("MQTT connect timeout")
        return self._connected.is_set()

    def publish(self, topic: str, payload: str, retain: bool=False, qos: int=0):
        if not self._connected.is_set():
            log.warning("Publish while MQTT not connected: %s", topic)
        self.client.publish(topic, payload=payload, qos=qos, retain=retain)

    def stop(self):
        try:
            self.client.loop_stop()
        except Exception:
            pass
        try:
            self.client.disconnect()
        except Exception:
            pass

# ---------------- Fetching ----------------
def build_question(pair: str) -> str:
    # "3007.25" -> "300725"
    return pair.replace(".", "").strip()

def split_part_from_bytes(part: str, b: Optional[bytes]) -> Tuple[Optional[int], str]:
    """
    Interpret 4-byte BE payload depending on part:
    - 'u32': use full 32-bit
    - 'hi': use high 16 bits
    - 'lo': use low 16 bits
    Returns (raw_value, part_used)
    """
    if b is None or len(b) != 4:
        return None, part
    v = int.from_bytes(b, byteorder="big", signed=False)
    if part == "u32":
        return v, part
    elif part == "hi":
        return (v >> 16) & 0xFFFF, part
    elif part == "lo":
        return v & 0xFFFF, part
    else:
        # default to u32
        return v, "u32"

def decode_value(decode: str, raw: Optional[int]) -> Tuple[Optional[Any], str]:
    fn = DECODERS.get(decode)
    if not fn:
        return raw, f"value = {raw!r}"
    if fn is percent_from_bucket:
        out = fn(raw)
        return out, "value = percent_from_bucket(raw)"
    elif fn is _div10:
        out = fn(raw)
        return out, "value = raw/10.0"
    elif fn is _div1000:
        out = fn(raw)
        return out, "value = raw/1000.0"
    elif fn is _times1000:
        out = fn(raw)
        return out, "value = _times1000(raw)"
    elif fn is _hours_from_seconds_u32:
        out = fn(raw)
        return out, "value = raw/3600.0"
    else:
        out = fn(raw)
        return out, "value = _id(raw)"

def fetch_bytes_with_templates(session: Session, ip: str, question: str, templates: List[str]) -> Tuple[Optional[bytes], str]:
    """
    Try each template in order until one returns 4 raw bytes.
    The {ip} and {question} placeholders will be formatted.
    Returns (bytes or None, template_var_name)
    """
    # We name variables qs1, qs2... so the log shows a *variable name* not the literal string
    for idx, tmpl in enumerate(templates, start=1):
        var_name = f"qs{idx}"
        url = tmpl.format(ip=ip, question=question)
        try:
            r = session.get(url, timeout=5)
            if r.status_code == 200:
                # Accept raw bytes (len 4) or hex string
                content = r.content
                if len(content) == 4:
                    return content, var_name
                # Try parse as plain hex in body or JSON {"bytes":"00112233"}
                txt = r.text.strip()
                if len(txt) == 8 and all(c in "0123456789abcdefABCDEF" for c in txt):
                    return bytes.fromhex(txt), var_name
                try:
                    j = r.json()
                    if isinstance(j, dict):
                        hb = j.get("bytes") or j.get("data") or j.get("raw")
                        if isinstance(hb, str) and len(hb.strip()) == 8:
                            return bytes.fromhex(hb.strip()), var_name
                except Exception:
                    pass
        except requests.RequestException as e:
            log.warning("fetch error on %s: %s", var_name, e)
    return None, "qs_none"

# ---------------- Polling ----------------
def publish_sensor(bus: MqttBus, base: str, name: str, sensor_key: str, spec: Dict[str, Any],
                   bytes_data: Optional[bytes], raw_val: Optional[int], value: Optional[Any]):
    unit = spec.get("unit")
    topic = f"{base}/{slugify(sensor_key)}"
    # Payload: null if value is None else JSON-encoded primitive
    payload = "null" if value is None else json.dumps(value)
    log.info("[%s] model=%s question_var=%s key=%s pair=%s question=%s encoding=%s bytes=%s raw=%s calc=%s%s topic=%s",
             name,
             spec.get("_model"),
             spec.get("_question_var"),
             sensor_key,
             spec.get("pair"),
             spec.get("_question"),
             f"{spec.get('part')}/{spec.get('decode')}",
             (bytes_data.hex() if bytes_data else ""),
             (raw_val if raw_val is not None else "None"),
             spec.get("_calc_str"),
             (f" {unit}" if unit else ""),
             topic)
    bus.publish(topic, payload, retain=True)

def poll_device_once(bus: MqttBus, session: Session, ip: str, name: str, device_type: str,
                     discovery_prefix: str, question_templates: List[str]):
    sensors = MODEL_MAP.get(device_type)
    if not sensors:
        log.error("[%s] Unknown device_type=%s", name, device_type)
        return

    base = f"atlas_copco/{slugify(name)}/sensor"

    for key, spec0 in sensors.items():
        spec = dict(spec0)  # copy
        spec["_model"] = device_type

        pair = spec["pair"]
        part = spec["part"]
        decode = spec["decode"]
        unit = spec.get("unit")

        question = build_question(pair)
        bytes_data, qvar = fetch_bytes_with_templates(session, ip, question, question_templates)
        spec["_question_var"] = qvar
        spec["_question"] = question

        raw_val, used_part = split_part_from_bytes(part, bytes_data)

        value, calc_str = decode_value(decode, raw_val)
        spec["_calc_str"] = calc_str

        publish_sensor(bus, base, name, key, spec, bytes_data, raw_val, value)

# ---------------- Main ----------------
def main():
    # Config precedence: env -> config.yml -> defaults
    cfg_path = os.environ.get("ACPARSER_CONFIG", "/config/config.yml")
    cfg = read_yaml_config(cfg_path) if os.path.exists(cfg_path) else {}

    devices = cfg.get("devices") or []
    # Also allow env shortcuts:
    # ACPARSER_DEVICES="name,ip,model;name2,ip2,model2"
    env_devices = os.environ.get("ACPARSER_DEVICES")
    if env_devices and not devices:
        tmp = []
        for chunk in env_devices.split(";"):
            if not chunk.strip():
                continue
            name, ip, model = [x.strip() for x in chunk.split(",")]
            tmp.append({"name": name, "ip": ip, "device_type": model})
        devices = tmp

    if not devices:
        log.error("No devices configured. Set devices:[] in %s or ACPARSER_DEVICES env.", cfg_path)
        sys.exit(1)

    mqtt_host = os.environ.get("MQTT_HOST", cfg.get("mqtt", {}).get("host", "localhost"))
    mqtt_port = int(os.environ.get("MQTT_PORT", cfg.get("mqtt", {}).get("port", 1883)))
    mqtt_user = os.environ.get("MQTT_USER", cfg.get("mqtt", {}).get("user") or "")
    mqtt_password = os.environ.get("MQTT_PASSWORD", cfg.get("mqtt", {}).get("password") or "")
    mqtt_client_id = os.environ.get("MQTT_CLIENT_ID") or cfg.get("mqtt", {}).get("client_id") or "atlas_copco_parser"
    mqtt_tls = env_bool("MQTT_TLS", cfg.get("mqtt", {}).get("tls", False))

    discovery_prefix = cfg.get("discovery_prefix", "homeassistant")
    autodetect = env_bool("ACPARSER_AUTODETECT", str(cfg.get("autodetect", "true")).lower() in ("1","true","yes","on"))

    # Question URL templates
    # Configure these to match the device HTTP API. Each must include {ip} and {question}.
    question_templates = cfg.get("question_templates") or [
        "http://{ip}/q?m={question}",
        "http://{ip}/mem/{question}",
        "http://{ip}/api/mb?m={question}",
    ]

    # Log start
    log.info("%s starting...", APP_NAME)
    log.info("Sequential mode enabled (forced): polling one device at a time.")
    log.info("MQTT connect -> host=%s port=%s client_id=%s user=%s tls=%s",
             mqtt_host, mqtt_port, mqtt_client_id, ("set" if mqtt_user else "none"), "on" if mqtt_tls else "off")

    bus = MqttBus(mqtt_host, mqtt_port, mqtt_user or None, mqtt_password or None, client_id=mqtt_client_id, tls=mqtt_tls)
    bus.connect(timeout=10.0)

    # Graceful shutdown
    stop_evt = threading.Event()
    def handle_sig(signum, frame):
        log.info("signal %s received, exiting...", signum)
        stop_evt.set()

    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, handle_sig)

    session = requests.Session()

    # Sequential poll forever
    while not stop_evt.is_set():
        for dev in devices:
            ip = dev.get("ip")
            name = dev.get("name") or ip
            model = dev.get("device_type") or dev.get("model") or ""
            if not ip or not model:
                log.error("Skipping device with missing ip/model: %s", dev)
                continue
            try:
                poll_device_once(bus, session, ip, name, model, discovery_prefix, question_templates)
            except Exception as e:
                log.exception("[%s] poll error: %s", name, e)
            if stop_evt.is_set():
                break
        # sleep a short interval between rounds
        stop_evt.wait(10.0)

    bus.stop()
    log.info("shutdown complete.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        raise
    except Exception as e:
        log.exception("fatal: %s", e)
        sys.exit(1)
