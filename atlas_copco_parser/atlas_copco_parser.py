#!/usr/bin/env python3
# Atlas Copco Parser — Home Assistant add-on
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
VERSION = "0.9.0"

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



# -------------------- Translation overrides (per-item) --------------------
def merge_sensors(base: dict, overrides: dict) -> dict:
    out = dict(base)
    for k, om in (overrides or {}).items():
        nm = dict(out.get(k, {}))
        nm.update({kk: vv for kk, vv in om.items() if vv is not None})
        out[k] = nm
    return out

def load_per_item_translation_from_opts(opts: dict) -> None:
    """
    Read per-sensor entries from options:
      <key>_name => name
      <key>_key => pair
      <key>_encoding => part  (hi/lo/u32 or HiU16/LoU16/UInt32)
      <key>_calc => decode    (accepts hints like /1000, /10, /3600, *1000, bucket, 3000-, 6000-, or decoder id like _div1000)
    """
    global SENSORS
    enc_map = {"hi":"hi","hiu16":"hi","high":"hi","lo":"lo","lou16":"lo","low":"lo","u32":"u32","uint32":"u32"}
    hint_map = {
        "_div1000": ["div1000","/1000"],
        "_div10": ["div10","/10"],
        "_hours_from_seconds_u32": ["sec2h","/3600","seconds/3600"],
        "_times1000": ["*1000","x1000","mul1000"],
        "_percent_from_bucket": ["bucket","65831881","percent"],
        "_service_remaining_3000": ["3000-","servicea","a-"],
        "_service_remaining_6000": ["6000-","serviceb","b-"],
    }
    overrides = {}
    for key, meta in SENSORS.items():
        o = {}
        v = opts.get(f"{key}_name")
        if isinstance(v, str) and v.strip():
            o["name"] = v.strip()
        v = opts.get(f"{key}_key")
        if isinstance(v, str) and v.strip():
            o["pair"] = v.strip()
        v = opts.get(f"{key}_encoding")
        if isinstance(v, str) and v.strip():
            o["part"] = enc_map.get(v.strip().lower(), meta.get("part"))
        v = opts.get(f"{key}_calc")
        if isinstance(v, str) and v.strip():
            calc = v.strip()
            if calc.startswith("_"):
                # accept direct decoder id if known
                o["decode"] = calc if calc in DECODERS else meta.get("decode")
            else:
                c = calc.lower().replace(" ", "")
                chosen = None
                for fn, hints in hint_map.items():
                    if any(h in c for h in hints):
                        chosen = fn
                        break
                if chosen:
                    o["decode"] = chosen
        if o:
            overrides[key] = o
    if overrides:
        SENSORS = merge_sensors(SENSORS, overrides)
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


def mqtt_discovery(cli: mqtt.Client, base_slug: str, name: str, discovery_prefix: str):
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
    }
    avail_topic = f"{base_slug}/availability"
    for key, meta in SENSORS.items():
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
           mqtt_settings: dict, scaling_overrides: Dict[str, float], question_hex: str):
    base_slug = slugify(name or ip)
    cli = mqtt.Client(client_id=f"mk5s_{base_slug}", clean_session=True)
    if mqtt_settings.get("user") or mqtt_settings.get("password"):
        cli.username_pw_set(mqtt_settings.get("user",""), mqtt_settings.get("password",""))
    avail_topic = f"{base_slug}/availability"
    cli.will_set(avail_topic, payload="offline", retain=True)
    cli.connect(mqtt_settings["host"], int(mqtt_settings["port"]), keepalive=60)

    mqtt_discovery(cli, base_slug, name, mqtt_settings["discovery_prefix"])
    cli.publish(avail_topic, "online", retain=True)

    session = requests.Session()

    qhex = re.sub(r"\s+", "", (question_hex or QUESTION_HEX))
    keys = build_keys_from_question(qhex)

    while not stop_event.is_set():
        print(f"[mk5s:{ip}] ==== decode cycle @ {time.strftime('%Y-%m-%d %H:%M:%S')} ====", flush=True)
        # Single-shot request
        try:
            resp = session.post(f"http://{ip}/cgi-bin/mkv.cgi", data={"QUESTION": qhex}, timeout=timeout)
            raw = resp.text if resp.status_code == 200 else ""
        except Exception as e:
            raw = f"EXC:{e}"
        clean = clean_answer(raw)
        tokens = tokenize_answer(clean, len(keys))
        if verbose:
            print(f"[mk5s:{ip}] Q_SINGLE(len={len(qhex)})={qhex}", flush=True)
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
        for key, meta in SENSORS.items():
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
    try:
        with open(OPTIONS_PATH, "r") as f:
            opts = json.load(f)
    except Exception:
        opts = {}

    # Apply per-item translation overrides
    load_per_item_translation_from_opts(opts)

    ip_list = csv_list(opts.get("ip_list", ""))
    name_list = csv_list(opts.get("name_list", ""))
    interval_list = csv_list(opts.get("interval_list", ""))
    question_list = csv_list(opts.get("question_list", ""))
    timeout_list = csv_list(opts.get("timeout_list", ""))
    verbose_list = csv_list(opts.get("verbose_list", ""))

    try:
        scaling_overrides = json.loads(opts.get("scaling_overrides", "{}"))
    except Exception:
        scaling_overrides = {}

    if not ip_list:
        ip_list = ["10.60.23.11"]

    def pick(lst: List[str], i: int, default: str) -> str:
        if not lst:
            return default
        return lst[i] if i < len(lst) and lst[i] != "" else (lst[-1] if lst[-1] != "" else default)

    mqtt_settings = {
        "host": opts.get("mqtt_host", "localhost"),
        "port": opts.get("mqtt_port", 1883),
        "user": opts.get("mqtt_user", ""),
        "password": opts.get("mqtt_password", ""),
        "discovery_prefix": opts.get("discovery_prefix", "homeassistant"),
    }

    log_banner()

    threads: List[threading.Thread] = []
    for i, ip in enumerate(ip_list):
        name = pick(name_list, i, ip)
        qhex = question_list[i]
        try:
            interval = int(pick(interval_list, i, "10"))
        except Exception:
            interval = 10
        try:
            timeout = int(pick(timeout_list, i, "5"))
        except Exception:
            timeout = 5
        verbose = pick(verbose_list, i, "false").lower() in ("1","true","yes","on")

        print(f"[mk5s] starting: host={ip} name={name} interval={interval}s timeout={timeout} verbose={verbose}", flush=True)
        t = threading.Thread(target=worker,
                             args=(i, ip, name, interval, timeout, verbose, mqtt_settings, scaling_overrides),
                             daemon=True)
        threads.append(t)
        t.start()

    def handle_sigterm(signum, frame):
        stop_event.set()
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=5.0)

if __name__ == "__main__":
    main()
