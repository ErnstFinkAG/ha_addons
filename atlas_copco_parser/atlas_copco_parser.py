#!/usr/bin/env python3
import os, json, threading, time, signal, re, logging, hashlib
from typing import Dict, Any, List, Optional, Tuple
import requests
import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"
VERSION = "0.1.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("atlas_copco")

def _calc_desc(decoder_name: str, raw_val):
    try:
        name = str(decoder_name)
    except Exception:
        name = str(decoder_name)
    if name in ("_div10", "div10"):
        return "value = raw/10.0"
    if name in ("_div100", "div100"):
        return "value = raw/100.0"
    if name in ("_div1000", "div1000"):
        return "value = raw/1000.0"
    if name in ("_hours_from_seconds_u32", "hours_from_seconds_u32"):
        return "value = raw/3600.0"
    if name in ("_percent_from_bucket", "percent_from_bucket"):
        return "value = percent_from_bucket(raw)"
    if name in ("_identity", "identity"):
        return "value = raw"
    return f"value = {name}(raw)"

def normalize_model(s: str) -> str:
    s = (s or "").strip().upper()
    aliases = {
        "GA15VS23A": "GA15VS23A",
        "GA15-VS23A": "GA15VS23A",
        "VS23A": "GA15VS23A",
        "GA15VP13": "GA15VP13",
        "GA15-VP13": "GA15VP13",
        "VP13": "GA15VP13",
    }
    return aliases.get(s, s)

def try_probe_model(sess: requests.Session, ip: str, timeout: int, verbose: bool=False) -> str:
    b_vs = get_pair_bytes(sess, ip, "3002.01", timeout=timeout, verbose=verbose) or b""
    b_vp = get_pair_bytes(sess, ip, "3002.08", timeout=timeout, verbose=verbose) or b""
    if b_vs and not b_vp:
        return "GA15VS23A"
    if b_vp and not b_vs:
        return "GA15VP13"
    if len(b_vs) >= len(b_vp) and b_vs:
        return "GA15VS23A"
    if b_vp:
        return "GA15VP13"
    return "GA15VS23A"

# ---------------- Controller Question strings (when bulk reads are supported) ----------------
QUESTION_GA15VS23A = (
    "30020130022430022630022730022a30026630032130032230032e30032f30033030070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071730071830071b30072530072630072730074330074c30074d30075430075530075630075730210130210530210a30220130220a30051f30052030052130052730052830052930052a300e03300e04300e05300e2a300ef3310e23310e27310e2b310e3b31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300909300914300108"
)
QUESTION_GA15VP13 = (
    "30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300108"
)

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

# ---------------- Decoders ----------------
def _id(v: int) -> int: return v
def _div10(v: int) -> float: return round(v / 10.0, 1)
def _div1000(v: int) -> float: return round(v / 1000.0, 3)
def _hours_from_seconds_u32(v: int) -> float: return round(v / 3600.0, 1)
def _percent_from_bucket(v: int) -> float: return round((v / 65831881.0) * 100.0, 2)
def _times1000(v: int) -> int: return v * 1000

DECODERS = {
    "_id": _id,
    "_div10": _div10,
    "_div1000": _div1000,
    "_hours_from_seconds_u32": _hours_from_seconds_u32,
    "_percent_from_bucket": _percent_from_bucket,
    "_times1000": _times1000,
}

# ---------------- Helpers ----------------
def hexstr_to_bytes(s: str) -> bytes:
    s = re.sub(r"[^0-9A-Fa-f]", "", s)
    if len(s) % 2:
        s = s[:-1]
    return bytes.fromhex(s)

def get_pair_bytes(session: requests.Session, ip: str, pair: str, timeout: int, verbose: bool=False) -> Optional[bytes]:
    # Fallback: query each pair separately. Many controllers accept "QUESTION=300201" (dot removed).
    q = pair.replace(".", "")
    try:
        r = session.post(f"http://{ip}/cgi-bin/mkv.cgi", data={"QUESTION": q}, timeout=timeout)
        if r.status_code != 200:
            return None
        data = hexstr_to_bytes(r.text)
        if verbose:
            log.debug("pair %s raw=%r bytes=%s", pair, r.text[:80], data.hex())
        return data
    except Exception as e:
        if verbose:
            log.warning("pair %s exc: %s", pair, e)
        return None

def parse_value(part: str, b: bytes) -> Optional[int]:
    # Interpret response bytes using simple conventions:
    #  - u32: 4 bytes big-endian (if more, take first 4)
    #  - hi: 2 bytes high word (bytes 0..1)
    #  - lo: 2 bytes low word (bytes 2..3) if we have 4+ bytes, else first 2 if only 2 came back
    if not b:
        return None
    if part == "u32":
        b2 = (b + b"\x00\x00\x00\x00")[:4]
        return int.from_bytes(b2, "big", signed=False)
    elif part == "hi":
        b2 = (b + b"\x00\x00")[:2]
        return int.from_bytes(b2, "big", signed=False)
    elif part == "lo":
        if len(b) >= 4:
            return int.from_bytes(b[2:4], "big", signed=False)
        else:
            b2 = (b + b"\x00\x00")[:2]
            return int.from_bytes(b2, "big", signed=False)
    else:
        return None

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", s.lower())

# ---------------- MQTT ----------------
class MqttBus:
    def __init__(self, host: str, port: int, user: str, password: str, client_id: str):
        self.client = mqtt.Client(client_id=client_id, clean_session=True)
        if user or password:
            self.client.username_pw_set(user, password)
        self.connected = threading.Event()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.will_set("atlas_copco/bridge/availability", "offline", qos=1, retain=True)
        self.client.connect(host, port, keepalive=60)
        self.thread = threading.Thread(target=self.client.loop_forever, daemon=True)
        self.thread.start()
        # Wait briefly for connect (non-blocking overall if broker is slow)
        self.connected.wait(timeout=5)

    def _on_connect(self, client, userdata, flags, rc):
        log.info("MQTT connected rc=%s", rc)
        self.client.publish("atlas_copco/bridge/availability", "online", qos=1, retain=True)
        self.connected.set()

    def _on_disconnect(self, client, userdata, rc):
        log.warning("MQTT disconnected rc=%s", rc)
        self.connected.clear()

    def pub(self, topic: str, payload: str, retain: bool=True, qos: int=1):
        self.client.publish(topic, payload, retain=retain, qos=qos)

# ---------------- Discovery ----------------
def publish_discovery(bus: MqttBus, discovery_prefix: str, device_name: str, device_type: str, sensors: Dict[str, Dict[str, Any]]):
    device_slug = slugify(device_name)
    base_state = f"atlas_copco/{device_slug}/sensor"
    avail = f"atlas_copco/{device_slug}/availability"
    dev = {
        "identifiers": [f"atlas_copco_{device_slug}"],
        "manufacturer": "Atlas Copco",
        "model": device_type,
        "name": device_name,
        "sw_version": VERSION,
    }
    for key, meta in sensors.items():
        sensor_slug = slugify(key)
        state_topic = f"{base_state}/{sensor_slug}"
        unique_id = f"ac_{device_slug}_{sensor_slug}"
        cfg = {
            "name": meta.get("name", key.replace("_", " ").title()),
            "state_topic": state_topic,
            "availability_topic": avail,
            "unique_id": unique_id,
            "device": dev,
        }
        if meta.get("unit"): cfg["unit_of_measurement"] = meta["unit"]
        if meta.get("device_class"): cfg["device_class"] = meta["device_class"]
        if meta.get("state_class"): cfg["state_class"] = meta["state_class"]

        topic = f"{discovery_prefix}/sensor/atlas_copco_{device_slug}/{sensor_slug}/config"
        bus.pub(topic, json.dumps(cfg), retain=True)

# ---------------- Worker ----------------
def poll_device(bus: MqttBus, ip: str, device_name: str, device_type: str, interval: int, timeout: int, verbose: bool, discovery_prefix: str):
    sensors = SENSORS_GA15VS23A if device_type == "GA15VS23A" else SENSORS_GA15VP13
    device_slug = slugify(device_name)
    avail = f"atlas_copco/{device_slug}/availability"

    publish_discovery(bus, discovery_prefix, device_name, device_type, sensors)
    bus.pub(avail, "online", retain=True)

    sess = requests.Session()

    while True:
        started = time.time()
        for key, meta in sensors.items():
            val = None
            b = get_pair_bytes(sess, ip, meta["pair"], timeout=timeout, verbose=verbose)
            if b is not None:
                raw = parse_value(meta["part"], b)
                if raw is not None:
                    dec = DECODERS[meta["decode"]]
                    try:
                        val = dec(raw)
                    except Exception as e:
                        if verbose:
                            log.warning("[%s] decode %s failed: %s", device_name, key, e)
            topic = f"atlas_copco/{device_slug}/sensor/{slugify(key)}"
            payload = "null" if val is None else json.dumps(val)
            bus.pub(topic, payload, retain=True)
            if verbose:
                log.info("[%s] %s = %s", device_name, key, payload)

        # pacing
        delay = max(0.5, interval - (time.time() - started))
        time.sleep(delay)

# ---------------- Main ----------------
def load_options() -> Dict[str, Any]:
    # When running as HA add-on, options are provided here:
    if os.path.exists(OPTIONS_PATH):
        with open(OPTIONS_PATH, "r") as f:
            return json.load(f)
    # For local testing, allow env vars
    return {
        "ip_list": os.environ.get("IP_LIST", ""),
        "name_list": os.environ.get("NAME_LIST", ""),
        "interval_list": os.environ.get("INTERVAL_LIST", ""),
        "timeout_list": os.environ.get("TIMEOUT_LIST", ""),
        "verbose_list": os.environ.get("VERBOSE_LIST", ""),
        "question": os.environ.get("QUESTION", "GA15VS23A"),
        "mqtt_host": os.environ.get("MQTT_HOST", "localhost"),
        "mqtt_port": int(os.environ.get("MQTT_PORT", "1883")),
        "mqtt_user": os.environ.get("MQTT_USER", ""),
        "mqtt_password": os.environ.get("MQTT_PASSWORD", ""),
        "discovery_prefix": os.environ.get("DISCOVERY_PREFIX", "homeassistant"),
    }

def parse_csv_list(s: str, fallback: Any, conv=lambda x: x):
    s = (s or "").strip()
    if not s:
        return fallback
    return [conv(x.strip()) for x in s.split(",") if x.strip() != ""]

def main():
    opts = load_options()

    ips = parse_csv_list(opts.get("ip_list", ""), [], str)
    names = parse_csv_list(opts.get("name_list", ""), [], str)
    intervals = parse_csv_list(opts.get("interval_list", ""), [10]*len(ips), int)
    timeouts = parse_csv_list(opts.get("timeout_list", ""), [5]*len(ips), int)
    verboses = parse_csv_list(opts.get("verbose_list", ""), [False]*len(ips), lambda x: x.lower() in ("1","true","yes","on"))
    qlist = parse_csv_list(opts.get("question_list", ""), [], str)
    default_q = opts.get("question", "GA15VS23A").strip() or "GA15VS23A"

    if len(names) != len(ips):
        names = [f"atlas_{i+1}" for i in range(len(ips))]
    if len(intervals) != len(ips):
        intervals = [intervals[0] if intervals else 10] * len(ips)
    if len(timeouts) != len(ips):
        timeouts = [timeouts[0] if timeouts else 5] * len(ips)
    if len(verboses) != len(ips):
        verboses = [verboses[0] if verboses else False] * len(ips)

    device_types = []
    for i in range(len(ips)):
        if i < len(qlist) and qlist[i]:
            device_types.append(qlist[i])
        else:
            device_types.append(default_q)

    mqtt_host = opts.get("mqtt_host", "localhost")
    mqtt_port = int(opts.get("mqtt_port", 1883))
    mqtt_user = opts.get("mqtt_user", "")
    mqtt_password = opts.get("mqtt_password", "")
    discovery_prefix = opts.get("discovery_prefix", "homeassistant")

    auto = bool(str(opts.get("autodetect", "true")).lower() in ("1","true","yes","on"))
    bus = MqttBus(mqtt_host, mqtt_port, mqtt_user, mqtt_password, client_id=f"atlas_copco_{int(time.time())}")

    threads = []
    stop = threading.Event()

    def handle_sig(signum, frame):
        log.info("signal %s received, exiting...", signum)
        stop.set()

    signal.signal(signal.SIGTERM, handle_sig)
    signal.signal(signal.SIGINT, handle_sig)

    for i, ip in enumerate(ips):
        name = names[i]
        device_type = device_types[i] if device_types[i] in ("GA15VS23A", "GA15VP13") else "GA15VS23A"
        t = threading.Thread(target=poll_device, args=(bus, ip, name, device_type, intervals[i], timeouts[i], verboses[i], discovery_prefix), daemon=True)
        t.start()
        threads.append(t)
        log.info("Started poller for %s (%s)", name, ip)

    # Keep main thread alive until stop signal
    try:
        while not stop.is_set():
            time.sleep(1)
    finally:
        # Announce offline for each device
        for i, ip in enumerate(ips):
            device_slug = slugify(names[i] if i < len(names) else f"atlas_{i+1}")
            avail = f"atlas_copco/{device_slug}/availability"
            bus.pub(avail, "offline", retain=True)
        log.info("shutdown complete.")

if __name__ == "__main__":
    main()

def poll_once(bus: MqttBus, sess: requests.Session, ip: str, device_name: str, device_type: str, timeout: int, verbose: bool, discovery_prefix: str):
    sensors = SENSORS_GA15VS23A if device_type == "GA15VS23A" else SENSORS_GA15VP13
    device_slug = slugify(device_name)
    base = f"atlas_copco/{device_slug}/sensor"
    avail = f"atlas_copco/{device_slug}/availability"

    for key, meta in sensors.items():
        val = None
        pair = meta["pair"]
        qstr = pair.replace(".", "")
        b = get_pair_bytes(sess, ip, pair, timeout=timeout, verbose=verbose)
        raw_int = None
        if b is not None:
            raw_int = parse_value(meta["part"], b)
            if raw_int is not None:
                dec = DECODERS[meta["decode"]]
                try:
                    val = dec(raw_int)
                except Exception as e:
                    if verbose:
                        log.warning("[%s] decode %s failed: %s", device_name, key, e)
        topic = f"{base}/{slugify(key)}"
        payload = "null" if val is None else json.dumps(val)
        bus.pub(topic, payload, retain=True)
        if verbose:
            unit = meta.get("unit")
            log.info(
                        "[%s] model=%s question_var=%s key=%s pair=%s question=%s encoding=%s/%s bytes=%s raw=%s calc=%s -> value=%s%s topic=%s",
                        device_name,
                        device_type,
                        device_type,
                        key,
                        pair,
                        qstr,
                        meta["part"],
                        meta["decode"],
                        None if b is None else b.hex(),
                        raw_int,
                        _calc_desc(meta["decode"], raw_int),
                        payload if payload != "null" else "null",
                        "" if not unit else f" {unit}",
                        topic
                    )
