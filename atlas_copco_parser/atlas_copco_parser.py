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

# ------------------------- PowerShell QUESTION (exact) ------------------------
QUESTION_HEX_GS15VP13 = (
    "30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300108"
)

QUESTION_HEX_GS15VS23A = (
    "30020130022430022630022730022a30026630032130032230032e30032f30033030070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071730071830071b30072530072630072730074330074c30074d30075430075530075630075730210130210530210a30220130220a30051f30052030052130052730052830052930052a300e03300e04300e05300e2a300ef3310e23310e27310e2b310e3b31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300909300914300108"
)

# Selected per add-on option 'type': 'gs15vp13' or 'gs15vs23a'
QUESTION_HEX = QUESTION_HEX_GS15VP13  # default; overridden at runtime

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
    \"\\"Tokenize a device answer into 32-bit words (8 hex) with 'X' runs meaning a *single* missing token.
    We consume a *full* run of X/x characters as one placeholder to keep alignment.
    Any non-hex noise is skipped with resync until we find 8 hex digits or an X-run.
    \"\\"
    tokens: List[Optional[str]] = []
    i = 0
    n = len(answer_clean)
    hexset = set("0123456789abcdefABCDEF")
    while len(tokens) < key_count and i < n:
        ch = answer_clean[i]
        if ch in ('X','x'):
            # consume the entire X-run as ONE missing token
            j = i + 1
            while j < n and answer_clean[j] in ('X','x'):
                j += 1
            tokens.append(None)
            i = j
        else:
            # try 8 clean hex chars
            if i + 8 <= n and all(c in hexset for c in answer_clean[i:i+8]):
                tokens.append(answer_clean[i:i+8].upper())
                i += 8
            else:
                # resync: skip until next hex or X
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

    "service_3000_hours":     {"pair":"3009.06","part":"u32","decode":"_service_remaining_3000","unit":"h","device_class":"duration","state_class":"measurement","name":"Service 3000h Remaining"},
    "service_6000_hours":     {"pair":"3009.07","part":"u32","decode":"_service_remaining_6000","unit":"h","device_class":"duration","state_class":"measurement","name":"Service 6000h Remaining"},

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
           mqtt_settings: dict, scaling_overrides: Dict[str, float], qhex):
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

    keys = build_keys_from_question(qhex)

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
            print(f"[mk5s:{ip}] Q_SINGLE(len={len(qhex)})={QUESTION_HEX}", flush=True)
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

    # Accept scalar or CSV for these three keys (aligned by index)
    ips = csv_list(opts.get("ip", ""))
    names = csv_list(opts.get("name", ""))
    types = [t.lower() for t in csv_list(opts.get("type", ""))]

    # Backward-compat: also look at legacy *_list keys if scalar keys empty
    if not ips:
        ips = csv_list(opts.get("ip_list", ""))
    if not names:
        names = csv_list(opts.get("name_list", ""))
    # Legacy didn't have types; default to gs15vp13 when missing
    if not types and opts.get("type"):
        types = [str(opts.get("type","gs15vp13")).lower()]
    if not types:
        # If not provided at all, assume all are gs15vp13
        types = ["gs15vp13"] * max(1, len(ips))

    # Expand lengths to the longest provided, filling sensible defaults
    n = max(len(ips), len(names), len(types), 1)
    if len(ips) < n:
        ips += [ips[-1] if ips else "10.60.23.11"] * (n - len(ips))
    if len(names) < n:
        names += [f"compressor_{i+1}" for i in range(len(names), n)]
    if len(types) < n:
        types += [types[-1] if types else "gs15vp13"] * (n - len(types))

    interval = int(opts.get("interval", 10))
    timeout = int(opts.get("timeout", 5))
    verbose = str(opts.get("verbose", "false")).lower() in ("1","true","yes","on")

    try:
        scaling_overrides = json.loads(opts.get("scaling_overrides", "{}"))
    except Exception:
        scaling_overrides = {}

    mqtt_settings = {
        "host": opts.get("mqtt_host", "core-mosquitto"),
        "port": int(opts.get("mqtt_port", 1883)),
        "user": opts.get("mqtt_user", ""),
        "password": opts.get("mqtt_password", ""),
        "discovery_prefix": opts.get("discovery_prefix", "homeassistant"),
    }

    log_banner()
    print(f"[mk5s] controllers={n} interval={interval}s timeout={timeout} verbose={verbose}", flush=True)

    threads = []
    for idx in range(n):
        type_str = types[idx]
        # Pick QUESTION_HEX for each worker without touching global used by others
        qhex = QUESTION_HEX_GS15VS23A if type_str in ("gs15vs23a","ga15vs23a") else QUESTION_HEX_GS15VP13
        t = threading.Thread(target=worker,
                             args=(idx, ips[idx], names[idx], interval, timeout, verbose, mqtt_settings, scaling_overrides, qhex),
                             daemon=True)
        t.start()
        threads.append(t)
        print(f"[mk5s] #{idx+1}: ip={ips[idx]} name={names[idx]} type={type_str}", flush=True)

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

    main()

    main()
