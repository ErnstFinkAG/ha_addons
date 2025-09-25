
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atlas Copco Parser (MQTT bridge)
Version: 0.0.9

- Detailed per-metric logging (pair, question, part/decoder, bytes, raw, calc, value)
- Sequential polling mode (no parallel threads) to avoid key/value mixups
- Correct GA15VS23A / GA15VP13 sensor maps (provided by user)
- Legacy env fallback (AC_HOSTS/AC_MODELS/AC_NAMES) + YAML/JSON support
- MQTT discovery prefix & topic slugging
- Publishes "null" when a value is missing
"""

import os
import sys
import time
import json
import yaml
import queue
import signal
import logging
import requests
from typing import Any, Dict, List, Tuple, Optional

__version__ = "0.0.9"

# --------------- Logging ---------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("atlas_copco_parser")

# --------------- MQTT ---------------
try:
    import paho.mqtt.client as mqtt
except Exception as e:
    logger.error("Missing dependency paho-mqtt. Add it to your image/venv. (%s)", e)
    raise

class MqttBus:
    def __init__(self, host: str, port: int, user: Optional[str], pwd: Optional[str], client_id: str):
        self.host = host
        self.port = port
        self.user = user
        self.pwd = pwd
        self.client_id = client_id
        self.client = mqtt.Client(client_id=self.client_id, clean_session=True, protocol=mqtt.MQTTv311)
        if self.user:
            self.client.username_pw_set(self.user, self.pwd or "")
        self.connected = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):
        logging.info("MQTT connected rc=%s", rc)
        self.connected = (rc == 0)

    def _on_disconnect(self, client, userdata, rc):
        logging.info("MQTT disconnected rc=%s", rc)
        self.connected = False

    def start(self):
        try:
            self.client.connect(self.host, self.port, keepalive=30)
        except Exception as e:
            logging.error("MQTT connect error: %s:%s -> %s", self.host, self.port, e)
        self.client.loop_start()

    def stop(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def publish(self, topic: str, payload: str, retain: bool=False, qos: int=0):
        try:
            self.client.publish(topic, payload=payload, qos=qos, retain=retain)
        except Exception as e:
            logging.error("MQTT publish error topic=%s err=%s", topic, e)


# --------------- Utils ---------------
def slugify(s: str) -> str:
    s = s.strip().lower().replace(" ", "_")
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-"
    s = "".join(ch if ch in allowed else "_" for ch in s)
    s = "_".join(filter(None, s.split("_")))
    return s

def _csv_env(name: str) -> List[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]

def legacy_env_devices() -> List[Dict[str, Any]]:
    """
    Back-compat for simple env config:
      AC_HOSTS (or DEV_IPS / ATLAS_COPCO_IPS)
      AC_MODELS (or DEV_MODELS)
      AC_NAMES (optional)
      TIMEOUT (optional, float)
      VERBOSE (optional, bool)
    """
    hosts  = _csv_env("AC_HOSTS") or _csv_env("DEV_IPS") or _csv_env("ATLAS_COPCO_IPS")
    models = _csv_env("AC_MODELS") or _csv_env("DEV_MODELS")
    names  = _csv_env("AC_NAMES")  or _csv_env("DEV_NAMES")

    if not hosts or not models:
        return []

    n = min(len(hosts), len(models))
    if names and len(names) < n:
        names += [f"device{i+1}" for i in range(len(names), n)]
    if not names:
        names = [f"device{i+1}" for i in range(n)]

    try:
        timeout = float(os.getenv("TIMEOUT", "2.5"))
    except Exception:
        timeout = 2.5
    verbose = str(os.getenv("VERBOSE", "true")).lower() in ("1","true","yes","on")

    devices = []
    for i in range(n):
        devices.append({
            "name":  names[i],
            "ip":    hosts[i],
            "model": models[i],
            "timeout": timeout,
            "verbose": verbose,
        })
    return devices

# --------------- Sensor maps (as provided) ---------------
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

MODEL_MAP = {
    "GA15VS23A": SENSORS_GA15VS23A,
    "GA15VP13":  SENSORS_GA15VP13,
}

# --------------- Decoders ---------------
def _id(x: Optional[int]) -> Optional[int]:
    return None if x is None else int(x)

def _div10(x: Optional[int]) -> Optional[float]:
    return None if x is None else x / 10.0

def _div1000(x: Optional[int]) -> Optional[float]:
    return None if x is None else x / 1000.0

def _times1000(x: Optional[int]) -> Optional[int]:
    return None if x is None else x * 1000

def _hours_from_seconds_u32(x: Optional[int]) -> Optional[float]:
    return None if x is None else round(x / 3600.0, 1)

def percent_from_bucket(raw: Optional[int], total: Optional[int]) -> Optional[float]:
    if raw is None or not total or total <= 0:
        return None
    return round((raw / float(total)) * 100.0, 2)

DECODERS = {
    "_id": _id,
    "_div10": _div10,
    "_div1000": _div1000,
    "_times1000": _times1000,
    "_hours_from_seconds_u32": _hours_from_seconds_u32,
    "_percent_from_bucket": "SPECIAL",
}

# --------------- Polling impl ---------------
class DeviceSession:
    def __init__(self, ip: str, timeout: float):
        self.ip = ip
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"Connection": "close"})  # keep-alive seems flaky on some units

    def ask_question(self, question: str) -> Optional[bytes]:
        """
        Attempt a small set of common endpoints; return raw 4 bytes (big-endian) or None.
        NOTE: Actual endpoint paths vary by controller; we try a few.
        """
        paths = [
            f"http://{self.ip}/{question}",                 # e.g. http://IP/300705
            f"http://{self.ip}/q?code={question}",         # e.g. legacy cgi
            f"http://{self.ip}/values?obj={question}",     # another variant
        ]
        last_exc = None
        for url in paths:
            try:
                r = self.s.get(url, timeout=self.timeout)
                if r.status_code == 200 and r.content:
                    # Expect 4 bytes; if hex string, normalize.
                    data = r.content.strip()
                    if all(c in b"0123456789abcdefABCDEF" for c in data) and len(data) in (8, 10):
                        # hex ascii
                        hexstr = data.decode("ascii").strip()[:8]
                        return bytes.fromhex(hexstr)
                    # else assume raw 4-byte payload
                    if len(data) >= 4:
                        return data[:4]
            except Exception as e:
                last_exc = e
        if last_exc:
            raise last_exc
        return None

# --------------- Read & Decode helpers ---------------
def bytes_to_raw(part: str, bts: Optional[bytes]) -> Tuple[str, Optional[int]]:
    if not bts:
        return "", None
    hexbytes = bts.hex()
    if part == "u32":
        raw = int.from_bytes(bts, "big", signed=False)
        return hexbytes, raw
    elif part == "hi":
        if len(bts) < 4:
            return hexbytes, None
        raw = int.from_bytes(bts[0:2], "big", signed=False)
        return hexbytes, raw
    elif part == "lo":
        if len(bts) < 4:
            return hexbytes, None
        raw = int.from_bytes(bts[2:4], "big", signed=False)
        return hexbytes, raw
    else:
        # default u16
        raw = int.from_bytes(bts[:2], "big", signed=False)
        return hexbytes, raw

def decode_value(decode: str, raw: Optional[int], bucket_total: Optional[int]) -> Tuple[str, Optional[Any]]:
    if decode == "_percent_from_bucket":
        val = percent_from_bucket(raw, bucket_total)
        return "value = percent_from_bucket(raw)", val
    fn = DECODERS.get(decode)
    if fn == "SPECIAL" or fn is None:
        return f"value = {decode}(raw)", raw
    val = fn(raw)
    # pretty print
    if decode == "_hours_from_seconds_u32" and val is not None:
        return "value = raw/3600.0", val
    if decode == "_div10" and val is not None:
        return "value = raw/10.0", val
    if decode == "_div1000" and val is not None:
        return "value = raw/1000.0", val
    if decode == "_times1000" and val is not None:
        return "value = _times1000(raw)", val
    return f"value = {decode}(raw)", val

# --------------- Publish helper ---------------
def publish_metric(bus: MqttBus, base: str, key: str, val: Any):
    topic = f"{base}/{slugify(key)}"
    payload = "null" if val is None else json.dumps(val)
    bus.publish(topic, payload, retain=False)

# --------------- Config ---------------
def load_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    # Read YAML if present
    cfg_path = os.getenv("AC_CONFIG", "/config/config.yml")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error("Failed reading %s: %s", cfg_path, e)

    # Merge JSON env if provided
    try:
        env_json = os.getenv("ACPARSER_DEVICES", "")
        if env_json.strip():
            cfg.setdefault("devices", [])
            cfg["devices"].extend(json.loads(env_json))
    except Exception as e:
        logger.error("Invalid ACPARSER_DEVICES JSON: %s", e)

    devices = cfg.get("devices", [])
    if not devices:
        legacy = legacy_env_devices()
        if legacy:
            logger.info("Legacy env mode active: using AC_HOSTS/AC_MODELS (or DEV_* / ATLAS_COPCO_IPS).")
            cfg["devices"] = legacy
            devices = legacy

    if not devices:
        logger.error("No devices configured. Provide /config/config.yml, ACPARSER_DEVICES JSON, "
                     "or legacy envs AC_HOSTS and AC_MODELS.")
        sys.exit(1)

    # MQTT
    cfg.setdefault("mqtt", {})
    m = cfg["mqtt"]
    m.setdefault("host", os.getenv("MQTT_HOST") or os.getenv("AC_MQTT_HOST") or "localhost")
    m.setdefault("port", int(os.getenv("MQTT_PORT", "1883")))
    u = os.getenv("MQTT_USER", "") or None
    p = os.getenv("MQTT_PASSWORD", "") or None
    if "user" not in m and u is not None:
        m["user"] = u
    if "password" not in m and p is not None:
        m["password"] = p

    cfg.setdefault("discovery_prefix", os.getenv("DISCOVERY_PREFIX", "homeassistant"))
    cfg.setdefault("base_prefix", os.getenv("BASE_PREFIX", "atlas_copco"))
    return cfg

# --------------- Poll logic ---------------
STOP = False
def handle_sigterm(signum, frame):
    global STOP
    logging.info("signal %s received, exiting...", signum)
    STOP = True

signal.signal(signal.SIGTERM, handle_sigterm)

def compute_vsd_total(model: str, raws: Dict[str, Optional[int]]) -> Optional[int]:
    keys = ["vsd_1_20","vsd_20_40","vsd_40_60","vsd_60_80","vsd_80_100","vssd_80_100"]
    total = 0
    any_found = False
    for k in keys:
        if k in MODEL_MAP.get(model, {}):
            v = raws.get(k)
            if v is not None:
                total += v
                any_found = True
    return total if any_found else None

def poll_device_once(bus: MqttBus, sess: DeviceSession, ip: str, name: str, model: str,
                     timeout: float, verbose: bool, base_prefix: str):
    sensors = MODEL_MAP.get(model)
    if not sensors:
        logger.error("[%s] unknown model: %s", name, model)
        return

    base = f"{base_prefix}/{slugify(name)}/sensor"
    # First pass: gather raw u32 for VSD buckets to compute percent
    vsd_raws: Dict[str, Optional[int]] = {}
    for key, meta in sensors.items():
        if meta.get("decode") == "_percent_from_bucket":
            pair = meta["pair"]
            question = pair.replace(".", "")
            try:
                bts = sess.ask_question(question)
                hexbytes, raw = bytes_to_raw(meta["part"], bts)
                vsd_raws[key] = raw
            except Exception as e:
                logger.warning("pair %s exc: %r", pair, e)
                vsd_raws[key] = None
                continue
    bucket_total = compute_vsd_total(model, vsd_raws)

    # Second pass: log + publish each sensor
    for key, meta in sensors.items():
        pair = meta["pair"]
        question = pair.replace(".", "")
        part = meta["part"]
        decode = meta["decode"]
        unit = meta["unit"]

        calc_str = ""
        try:
            bts = sess.ask_question(question)
            hexbytes, raw = bytes_to_raw(part, bts)
            if decode == "_percent_from_bucket":
                calc_str, val = decode_value(decode, raw, bucket_total)
            else:
                calc_str, val = decode_value(decode, raw, None)
            # Detailed log line
            logging.info(
                "[%s] model=%s question_var=%s key=%s pair=%s question=%s encoding=%s/%s bytes=%s raw=%s calc=%s -> value=%s%s%s topic=%s",
                name, model, model, key, pair, question, part, decode, hexbytes, raw,
                calc_str, val, f" {unit}" if unit else "", "" , f"{base}/{slugify(key)}"
            )
            # Publish
            publish_metric(bus, base, key, val)
        except Exception as e:
            logger.warning("pair %s exc: %r", pair, e)
            logging.info(
                "[%s] model=%s question_var=%s key=%s pair=%s question=%s encoding=%s/%s bytes=%s raw=%s calc=%s -> value=%s topic=%s",
                name, model, model, key, pair, question, part, decode, None, None,
                "error", "null", f"{base}/{slugify(key)}"
            )
            publish_metric(bus, base, key, None)

def main():
    print("[atlas_copco_parser] starting...")
    cfg = load_config()

    mqtt_host = cfg.get("mqtt", {}).get("host", "localhost")
    mqtt_port = int(cfg.get("mqtt", {}).get("port", 1883))
    mqtt_user = cfg.get("mqtt", {}).get("user", None)
    mqtt_password = cfg.get("mqtt", {}).get("password", None)
    base_prefix = cfg.get("base_prefix", "atlas_copco")
    discovery_prefix = cfg.get("discovery_prefix", "homeassistant")

    auto = True  # reserved flag, not used now
    bus = MqttBus(mqtt_host, mqtt_port, mqtt_user, mqtt_password, client_id=f"atlas_copco_{int(time.time())}")
    bus.start()

    devices = cfg.get("devices", [])
    if not devices:
        logger.error("No devices configured. Set devices:[] in /config/config.yml or ACPARSER_DEVICES env.")
        sys.exit(1)

    logging.info("Sequential mode enabled (forced): polling one device at a time.")

    sessions: List[DeviceSession] = []
    for d in devices:
        ip = d.get("ip")
        timeout = float(d.get("timeout", 2.5))
        sessions.append(DeviceSession(ip, timeout))

    try:
        while not STOP:
            for i, d in enumerate(devices):
                ip = d.get("ip")
                name = d.get("name", f"device{i+1}")
                model = d.get("model")
                timeout = float(d.get("timeout", 2.5))
                verbose = bool(d.get("verbose", True))

                poll_device_once(bus, sessions[i], ip, name, model, timeout, verbose, base_prefix)
                if STOP:
                    break
            # single pass? if you want continuous loop, sleep and continue
            if str(os.getenv("ONE_SHOT", "false")).lower() in ("1","true","yes","on"):
                break
            time.sleep(float(os.getenv("POLL_INTERVAL", "10.0")))
    except KeyboardInterrupt:
        pass
    finally:
        bus.stop()
        logging.info("shutdown complete.")

if __name__ == "__main__":
    main()
