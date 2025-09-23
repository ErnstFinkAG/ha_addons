#!/usr/bin/env python3
# MK5s Client — Home Assistant add-on
# VERSION: 0.8.1-entityid-fix-2025-09-04
#
# This version mirrors the PowerShell script:
#   - One single QUESTION hex string (same order and content)
#   - Parse tokens strictly in sequence: 'X' -> missing, else 8 hex chars
#   - Map to named sensors and decode
#
# If a target field is missing ('X'), we do a single-pair fallback read.

import os, json, threading, time, signal, re, hashlib
from typing import Dict, Any, List, Optional, Tuple
import requests
import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"
SELF_PATH = __file__
VERSION = "0.8.1-entityid-fix-2025-09-04"

# ---------------- Configurable translation layer ----------------
def load_translation_from_opts(opts: Dict[str, Any]) -> None:
    """Allow overriding QUESTION_HEX and SENSORS via add-on options.
    Supported options:
      - translation_mode: 'built_in' (default), 'file', or 'inline'
      - translation_file: absolute path to JSON file (when mode=='file')
      - translation_inline: JSON string (when mode=='inline')
      - question: optional hex string override (legacy)
    JSON structure (file/inline):
    {
      "question_hex": "300201...",
      "sensors": {
        "pressure_bar": {"pair":"3002.01","part":"hi","decode":"_div1000","unit":"bar","device_class":"pressure","state_class":"measurement","name":"Pressure"}
      }
    }
    """
    global QUESTION_HEX, SENSORS
    mode = (opts.get("translation_mode") or "built_in").strip().lower()
    q_override = opts.get("question")
    data = None
    if mode == "file":
        path = opts.get("translation_file")
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"[atlas] translation_file load error: {e}", flush=True)
        else:
            print(f"[atlas] translation_file not found: {path}", flush=True)
    elif mode == "inline":
        j = opts.get("translation_inline")
        if j:
            try:
                data = json.loads(j)
            except Exception as e:
                print(f"[atlas] translation_inline parse error: {e}", flush=True)
    # Legacy question override
    if isinstance(q_override, str) and q_override.strip():
        QUESTION_HEX = re.sub(r"\s+", "", q_override.strip())
    # Apply JSON if present
    if isinstance(data, dict):
        if isinstance(data.get("question_hex"), str) and data.get("question_hex").strip():
            QUESTION_HEX = re.sub(r"\s+", "", data["question_hex"].strip())
        if isinstance(data.get("sensors"), dict) and data.get("sensors"):
            # Basic validation: ensure each sensor has a 'pair' and 'part'
            valid = {}
            for k, v in data["sensors"].items():
                if isinstance(v, dict) and v.get("pair") and v.get("part"):
                    # carry through other fields as-is
                    valid[k] = v
            if valid:
                SENSORS.update(valid)  # allow partial override / additions
                # Also drop sensors explicitly set to null
                for k, v in data["sensors"].items():
                    if v is None and k in SENSORS:
                        del SENSORS[k]
    print(f"[atlas] translation mode: {mode}; question_len={len(QUESTION_HEX)}; sensors={len(SENSORS)}", flush=True)


# ------------------------- PowerShell QUESTION (exact) ------------------------
QUESTION_HEX = (
    "300201300203300205300208"
    "30030130030230030a"
    "30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f300714300715300718300722300723300724"
    "30210130210530210a"
    "300501300502300504300505300507300508300509"
    "300e03300e04300e2a300e88"
    "31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f311360311361311362311363311364311365311366311367"
    "31140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412"
    "300901300906300907"
    "300108"
)


# -------------------- Per-device config & merge --------------------
def merge_sensors(base: dict, overrides: Optional[dict]) -> dict:
    """
    Merge base SENSORS with per-device overrides.
    Override keys: name, unit, device_class, state_class, part, decode, pair, kind, enabled (bool)
    Setting {"enabled": false} removes that sensor.
    Adding a new key adds a sensor (must specify pair/part/decode minimally).
    """
    if overrides is None:
        return dict(base)
    out = {}
    for k, meta in base.items():
        om = overrides.get(k) if isinstance(overrides, dict) else None
        if isinstance(om, dict) and om.get("enabled") is False:
            continue
        nm = dict(meta)
        if isinstance(om, dict):
            for fld in ("name","unit","device_class","state_class","part","decode","pair","kind"):
                if fld in om and om[fld] is not None:
                    nm[fld] = om[fld]
        out[k] = nm
    # additions
    for k, om in overrides.items():
        if k not in out and isinstance(om, dict):
            if om.get("enabled") is False:
                continue
            if not (om.get("pair") and om.get("part") and om.get("decode")):
                continue
            out[k] = dict(om)
    return out

def build_device_sensors(opts: dict, device: dict) -> Tuple[str, dict]:
    """
    Returns (question_hex, sensors_def) for a device by layering:
    1) Built-in QUESTION_HEX and SENSORS
    2) Global translation from opts (already applied to globals via load_translation_from_opts)
    3) Device-level 'question_hex' and 'translation' overrides
    4) Device-level 'sensors' overrides (enable/rename/tweak)
    """
    q = QUESTION_HEX
    sensors = dict(SENSORS)
    # device translation block like global JSON format
    dtr = device.get("translation")
    if isinstance(dtr, dict):
        if isinstance(dtr.get("question_hex"), str) and dtr["question_hex"].strip():
            q = re.sub(r"\s+","", dtr["question_hex"].strip())
        if isinstance(dtr.get("sensors"), dict):
            sensors = merge_sensors(sensors, dtr["sensors"])
    # direct device fields
    if isinstance(device.get("question_hex"), str) and device["question_hex"].strip():
        q = re.sub(r"\s+","", device["question_hex"].strip())
    if isinstance(device.get("sensors"), dict):
        sensors = merge_sensors(sensors, device["sensors"])
    return q, sensors
# ------------------------- Helpers ------------------------
def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def clean_answer(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r'[^0-9A-Fa-fXx]', '', s)

def build_keys_from_question(q: str) -> List[str]:
    ks: List[str] = []
    for i in range(0, len(q), 6):
        idx = q[i:i+4].upper()
        sub = q[i+4:i+6].upper()
        ks.append(f"{idx}.{sub}")
    return ks

def tokenize_answer(answer_clean: str, key_count: int) -> List[Optional[str]]:
    tokens: List[Optional[str]] = []
    i = 0
    n = len(answer_clean)
    while len(tokens) < key_count and i < n:
        ch = answer_clean[i]
        if ch in ('X','x'):
            tokens.append(None)
            i += 1
        else:
            if i + 8 <= n and re.fullmatch(r'[0-9A-Fa-f]{8}', answer_clean[i:i+8]):
                tokens.append(answer_clean[i:i+8].upper())
                i += 8
            else:
                # resync
                i += 1
    # pad if short
    while len(tokens) < key_count:
        tokens.append(None)
    return tokens

def decode_part(u32_hex: str, part: str) -> Optional[int]:
    try:
        v = int(u32_hex, 16)
    except Exception:
        return None
    if part == "u32":
        return v
    elif part == "hi":
        return (v >> 16) & 0xFFFF
    elif part == "lo":
        return v & 0xFFFF
    return None

# ------------------------------ Decoders -------------------------------------
def _id(v: int) -> int:
    return v
def _div10(v: int) -> float:
    return round(v / 10.0, 1)
def _div1000(v: int) -> float:
    return round(v / 1000.0, 3)
def _hours_from_seconds_u32(v: int) -> float:
    return round(v / 3600.0, 1)
def _percent_from_bucket(v: int) -> float:
    return round((v / 65831881.0) * 100.0, 2)
def _service_remaining_3000(v: int) -> float:
    return max(0.0, round(3000.0 - (v / 3600.0), 1))
def _service_remaining_6000(v: int) -> float:
    return max(0.0, round(6000.0 - (v / 3600.0), 1))
def _times1000(v: int) -> int:
    return v * 1000

DECODERS = {
    "_id": _id,
    "_div10": _div10,
    "_div1000": _div1000,
    "_hours_from_seconds_u32": _hours_from_seconds_u32,
    "_percent_from_bucket": _percent_from_bucket,
    "_service_remaining_3000": _service_remaining_3000,
    "_service_remaining_6000": _service_remaining_6000,
    "_times1000": _times1000,
}

# ------------------------------ Sensors --------------------------------------
SENSORS: Dict[str, Dict[str, Any]] = {
    "pressure_bar":           {"pair":"3002.01","part":"hi", "decode":"_div1000","unit":"bar","device_class":"pressure","state_class":"measurement","name":"Pressure"},
    "element_outlet":         {"pair":"3002.03","part":"hi", "decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Element Outlet"},
    "ambient_air":            {"pair":"3002.05","part":"hi", "decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Ambient Air"},
    "controller_temperature": {"pair":"3002.08","part":"hi", "decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Controller Temperature"},

    "running_hours":          {"pair":"3007.01","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Running Hours"},
    "motor_starts":           {"pair":"3007.03","part":"lo", "decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Motor Starts"},
    "load_cycles":            {"pair":"3007.04","part":"lo", "decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Load Cycles"},
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
    "recirculation_starts":   {"pair":"3007.14","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Starts"},
    "recirculation_failures": {"pair":"3007.15","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"total_increasing","name":"Recirculation Failures"},
    "low_load_hours":         {"pair":"3007.18","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Low Load Hours"},
    "available_hours":        {"pair":"3007.22","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Available Hours"},
    "unavailable_hours":      {"pair":"3007.23","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Unavailable Hours"},
    "emergency_stop_hours":   {"pair":"3007.24","part":"u32","decode":"_hours_from_seconds_u32","unit":"h","device_class":"duration","state_class":"total_increasing","name":"Emergency Stop Hours"},

    "rpm_actual":             {"pair":"3021.01","part":"hi", "decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"RPM Actual"},
    "rpm_requested":          {"pair":"3021.01","part":"lo", "decode":"_id","unit":"rpm","device_class":None,"state_class":"measurement","name":"RPM Requested"},
    "current":                {"pair":"3021.05","part":"lo", "decode":"_id","unit":"A","device_class":"current","state_class":"measurement","name":"Current"},
    "flow":                   {"pair":"3021.0A","part":"hi", "decode":"_id","unit":"%","device_class":None,"state_class":"measurement","name":"Flow"},

    "fan_motor":              {"pair":"3005.01","part":"hi", "decode":"_id","unit":None,"device_class":"running","state_class":None,"kind":"binary_sensor","name":"Fan Motor"},

    "service_a":     {"pair":"3009.06","part":"u32","decode":"_service_remaining_3000","unit":"h","device_class":"duration","state_class":"measurement","name":"Service A Remaining"},
    "service_b":     {"pair":"3009.07","part":"u32","decode":"_service_remaining_6000","unit":"h","device_class":"duration","state_class":"measurement","name":"Service B Remaining"},

    "machine_status":         {"pair":"3001.08","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"measurement","name":"Machine Status"}
}

TARGET_PAIRS = { meta["pair"].upper(): key for key, meta in SENSORS.items() }

def slugify(s: str) -> str:
    return "".join(c.lower() if (c.isalnum() or c in "-_") else "_" for c in (s or ""))

def csv_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(",")] if s and s.strip() else []


def mqtt_discovery(cli: mqtt.Client, base_slug: str, name: str, discovery_prefix: str, sensors_def: dict):
    """
    Publish MQTT Discovery with clean entity ids:
    - node_id (topic segment) = base_slug
    - object_id = sensor key (no base_slug prefix)
    - name = human label only (no device name), HA shows device name in the device card
    Also: publish empty retained configs to potential legacy topics that used base_slug twice.
    """
    device = {
        "ids": [f"mk5s_{base_slug}"],
        "mf": "Atlas Copco",
        "mdl": "MK5s Touch",
        "name": name,
        "cns": [["ip".get("ip","")], ["host".get("hostname","")]],
    }
    avail_topic = f"{base_slug}/availability"
    for key, meta in sensors_def.items():
        is_binary = (meta.get("kind", "sensor") == "binary_sensor")
        platform = "binary_sensor" if is_binary else "sensor"
        # New, clean topic: .../<platform>/<node_id>/<object_id>/config  with object_id = key only
        conf_topic = f"{discovery_prefix}/{platform}/{base_slug}/{key}/config"
        # Potential legacy/bad topic where object_id mistakenly included base_slug
        legacy_conf_topic = f"{discovery_prefix}/{platform}/{base_slug}/{base_slug}_{key}/config"

        # Proactively clear legacy entity (if existed)
        try:
            cli.publish(legacy_conf_topic, payload="", retain=True)
        except Exception:
            pass

        state_topic = f"{base_slug}/{key}"
        payload: Dict[str, Any] = {
            # Friendly name: just the sensor label
            "name": meta.get("name", key.replace('_', ' ').title()),
            # Ensure uniqueness; include a namespace to be safe
            "uniq_id": f"mk5s:{base_slug}:{key}",
            "stat_t": state_topic,
            "avty_t": avail_topic,
            "dev": device,
            "qos": 0,
        }
        unit = meta.get("unit")
        if unit:
            payload["unit_of_meas"] = unit
        if meta.get("state_class"):
            payload["stat_cla"] = meta["state_class"]
        if meta.get("device_class"):
            payload["dev_cla"] = meta["device_class"]
        if is_binary:
            payload["pl_on"] = "1"
            payload["pl_off"] = "0"

        cli.publish(conf_topic, json.dumps(payload), retain=True)

stop_event = threading.Event()


def single_pair_read(session: requests.Session, ip: str, pair: str, timeout: int, verbose: bool) -> Optional[str]:
    q = pair.replace(".","")
    try:
        r = session.post(f"http://{ip}/cgi-bin/mkv.cgi", data={"QUESTION": q}, timeout=timeout)
        raw = r.text if r.status_code == 200 else ""
    except Exception as e:
        raw = f"EXC:{e}"
    clean = clean_answer(raw)
    toks = tokenize_answer(clean, 1)
    tok = toks[0] if toks else None
    if verbose:
        print(f"[mk5s:{ip}] FALLBACK_Q={q}", flush=True)
        print(f"[mk5s:{ip}] FALLBACK_A_RAW={repr(raw)}", flush=True)
        print(f"[mk5s:{ip}] FALLBACK_A_CLEAN={repr(clean)} TOKENS={len(toks)}", flush=True)
        print(f"[mk5s:{ip}]   token[fallback] {pair} = {tok if tok else 'None'}", flush=True)
    return tok

def worker(idx: int, ip: str, name: str, interval: int, timeout: int, verbose: bool,
           mqtt_settings: dict, scaling_overrides: Dict[str, float], sensors_def: dict):
    base_slug = slugify(name or ip)
    cli = mqtt.Client(client_id=f"mk5s_{base_slug}", clean_session=True)
    if mqtt_settings.get("user") or mqtt_settings.get("password"):
        cli.username_pw_set(mqtt_settings.get("user",""), mqtt_settings.get("password",""))
    avail_topic = f"{base_slug}/availability"
    cli.will_set(avail_topic, payload="offline", retain=True)
    cli.connect(mqtt_settings["host"], int(mqtt_settings["port"]), keepalive=60)

    mqtt_discovery(cli, base_slug, name, mqtt_settings["discovery_prefix"], sensors_def)
    cli.publish(avail_topic, "online", retain=True)

    session = requests.Session()

    keys = build_keys_from_question(QUESTION_HEX)

    while not stop_event.is_set():
        print(f"[mk5s:{ip}] ==== decode cycle @ {time.strftime('%Y-%m-%d %H:%M:%S')} ====", flush=True)
        # Single-shot request
        try:
            resp = session.post(f"http://{ip}/cgi-bin/mkv.cgi", data={"QUESTION": QUESTION_HEX}, timeout=timeout)
            raw = resp.text if resp.status_code == 200 else ""
        except Exception as e:
            raw = f"EXC:{e}"
        clean = clean_answer(raw)
        tokens = tokenize_answer(clean, len(keys))
        if verbose:
            print(f"[mk5s:{ip}] Q_SINGLE(len={len(QUESTION_HEX)})={QUESTION_HEX}", flush=True)
            print(f"[mk5s:{ip}] A_SINGLE_RAW={repr(raw)}", flush=True)
            print(f"[mk5s:{ip}] A_SINGLE_CLEAN(len={len(clean)}) TOKENS={len(tokens)}", flush=True)

        pair_raw: Dict[str, Optional[str]] = {}
        for k, tok in zip(keys, tokens):
            if verbose:
                print(f"[mk5s:{ip}]   token[single] {k} = {tok if tok else 'None'}", flush=True)
            pair_raw[k] = tok

        # Targeted fallbacks for fields that matter to HA
        for pair in list(TARGET_PAIRS.keys()):
            if pair_raw.get(pair) is None:
                tok = single_pair_read(session, ip, pair, timeout, verbose)
                if tok is not None:
                    pair_raw[pair] = tok

        # Decode & publish
        for key, meta in sensors_def.items():
            pair = meta["pair"].upper()
            raw8 = pair_raw.get(pair)
            if raw8 is None:
                partv = None
                calc = None
            else:
                partv = decode_part(raw8, meta["part"])
                if partv is None:
                    calc = None
                else:
                    dec = DECODERS[meta["decode"]]
                    try:
                        calc = dec(partv)
                    except Exception:
                        calc = None
                    if key in scaling_overrides and isinstance(calc, (int, float)):
                        try:
                            calc = calc * float(scaling_overrides[key])
                        except Exception:
                            pass
            state_topic = f"{base_slug}/{key}"
            cli.publish(state_topic, "unknown" if calc is None else str(calc), retain=True)
            # Log line
            raw_disp = raw8 if raw8 is not None else "X/None"
            int_disp = "—" if partv is None else str(partv)
            calc_disp = "unknown" if calc is None else f"{calc}{meta.get('unit') or ''}"
            print(f"[mk5s:{ip}] {key:<24} pair={pair:<7} part={meta['part']:<3} raw={raw_disp:<10} int={int_disp:<12} calc={calc_disp}", flush=True)

        # Sleep
        for _ in range(int(interval * 10)):
            if stop_event.is_set():
                break
            time.sleep(0.1)

def log_banner():
    sha = "unknown"
    try:
        sha = file_sha256(SELF_PATH)[:16]
    except Exception:
        pass
    print(f"[mk5s] mk5s_client.py VERSION={VERSION} SHA256[:16]={sha}", flush=True)


def main():
    # Read options
    with open("/data/options.json","r") as f:
        opts = json.load(f)

    # Global verbosity & scaling overrides
    verbose_list = (opts.get("verbose_list") or "false").split(",")
    scaling_overrides = {}  # reserved for future global scaling per key

    # Load global translation customization first
    try:
        load_translation_from_opts(opts)
    except Exception as e:
        print(f"[atlas] translation load warning: {e}", flush=True)

    # MQTT global settings (can be overridden per-device)
    mqtt_settings = {
        "host": opts.get("mqtt_host","localhost"),
        "port": opts.get("mqtt_port",1883),
        "user": opts.get("mqtt_user",""),
        "password": opts.get("mqtt_password",""),
        "discovery_prefix": opts.get("discovery_prefix","homeassistant").rstrip("/")
    }

    workers = []
    devices_json = opts.get("devices_json")
    if isinstance(devices_json, str) and devices_json.strip().startswith("["):
        try:
            devices = json.loads(devices_json)
        except Exception as e:
            print(f"[atlas] devices_json parse error: {e}", flush=True)
            devices = []
    else:
        # Legacy comma-separated lists
        ip_list = [x.strip() for x in (opts.get("ip_list") or "").split(",") if x.strip()]
        name_list = [x.strip() for x in (opts.get("name_list") or "").split(",") if x.strip()]
        interval_list = [x.strip() for x in (opts.get("interval_list") or "").split(",") if x.strip()]
        timeout_list = [x.strip() for x in (opts.get("timeout_list") or "").split(",") if x.strip()]
        devices = []
        for i, ip in enumerate(ip_list):
            devices.append({
                "ip": ip,
                "name": name_list[i] if i < len(name_list) else ip,
                "interval": int(interval_list[i]) if i < len(interval_list) else 10,
                "timeout": int(timeout_list[i]) if i < len(timeout_list) else 5,
            })

    # Launch a worker per device
    for idx, dev in enumerate(devices):
        ip = dev.get("ip")
        name = dev.get("name") or ip
        interval = int(dev.get("interval", 10))
        timeout = int(dev.get("timeout", 5))
        verbose = str(dev.get("verbose", verbose_list[0] if verbose_list else "false")).lower() in ("1","true","yes","on")
        # MQTT overrides
        dev_mqtt = dict(mqtt_settings)
        if isinstance(dev.get("mqtt"), dict):
            dev_mqtt.update({k: v for k,v in dev["mqtt"].items() if v not in (None,"")})
            if "discovery_prefix" in dev_mqtt:
                dev_mqtt["discovery_prefix"] = str(dev_mqtt["discovery_prefix"]).rstrip("/")
        # Build per-device sensors and question
        q, sensors_def = build_device_sensors(opts, dev)
        # Provide device info for discovery
        device_info = {"ip": ip}
        # Patch QUESTION_HEX in a thread-local manner by capturing q into closure
        def start_worker(i=idx, a_ip=ip, a_name=name, a_interval=interval, a_timeout=timeout, a_verbose=verbose, a_mqtt=dev_mqtt, a_sensors=sensors_def, a_q=q):
            global QUESTION_HEX
            saved_q = QUESTION_HEX
            QUESTION_HEX = a_q
            try:
                worker(i, a_ip, a_name, a_interval, a_timeout, a_verbose, a_mqtt, scaling_overrides, a_sensors, {"ip": a_ip})
            finally:
                QUESTION_HEX = saved_q
        t = threading.Thread(target=start_worker, daemon=True)
        workers.append(t)
        t.start()

    # Wait forever; handle SIGTERM elsewhere
    while True:
        time.sleep(60)

