#!/usr/bin/env python3
import os, json, threading, time, signal, re
from typing import Dict, Any, List, Optional, Tuple
import requests
import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"

# ------------------------- Verbose logging helpers ----------------------------
def vlog(enabled: bool, msg: str) -> None:
    if enabled:
        print(msg, flush=True)

def log_cycle_header(enabled: bool, ip: str) -> None:
    vlog(enabled, f"[mk5s:{ip}] ==== decode cycle @ {time.strftime('%Y-%m-%d %H:%M:%S')} ====")

def log_qna(enabled: bool, ip: str, pair: str, question_hex: str, answer: Optional[str], token: Optional[str]) -> None:
    if not enabled:
        return
    vlog(True, f"[mk5s:{ip}] Q({pair})={question_hex}  A_raw={repr(answer)}  A_tok={repr(token)}")

def log_value(enabled: bool, ip: str, key: str, pair: str, part: str, raw8: Optional[str], partv: Optional[int], calc: Optional[Any], unit: Optional[str]) -> None:
    if not enabled:
        return
    raw_disp = raw8 if raw8 is not None else "X/None"
    part_disp = str(partv) if partv is not None else "—"
    if calc is None:
        calc_disp = "unknown"
    else:
        calc_disp = str(calc) + (unit or "")
    vlog(True, f"[mk5s:{ip}] {key:<24} pair={pair:<7} part={part:<3} raw={raw_disp:<10} int={part_disp:<12} calc={calc_disp}")

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
    # UInt32 / 65,831,881 × 100
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
    "machine_status":         {"pair":"3001.08","part":"u32","decode":"_id","unit":None,"device_class":None,"state_class":"measurement","name":"Machine Status"},
    "pressure_bar":           {"pair":"3002.01","part":"hi", "decode":"_div1000","unit":"bar","device_class":"pressure","state_class":"measurement","name":"Pressure"},
    "element_outlet":         {"pair":"3002.03","part":"hi", "decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Element Outlet"},
    "ambient_air":            {"pair":"3002.05","part":"hi", "decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Ambient Air"},
    "controller_temperature": {"pair":"3002.08","part":"hi", "decode":"_div10","unit":"°C","device_class":"temperature","state_class":"measurement","name":"Controller Temperature"},
    "fan_motor":              {"pair":"3005.01","part":"hi", "decode":"_id","unit":None,"device_class":"running","state_class":None,"kind":"binary_sensor","name":"Fan Motor"},
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
    "service_3000_hours":     {"pair":"3009.06","part":"u32","decode":"_service_remaining_3000","unit":"h","device_class":"duration","state_class":"measurement","name":"Service 3000h Remaining"},
    "service_6000_hours":     {"pair":"3009.07","part":"u32","decode":"_service_remaining_6000","unit":"h","device_class":"duration","state_class":"measurement","name":"Service 6000h Remaining"},
}

PAIR_LIST: List[str] = sorted({meta["pair"].upper() for meta in SENSORS.values()},
                              key=lambda p: (int(p.split(".")[0],16), int(p.split(".")[1],16)))

# ------------------------------ HTTP helpers ---------------------------------
def question_from_pair(pair: str) -> str:
    return pair.replace(".","").upper()

def extract_token(answer_text: Optional[str]) -> Optional[str]:
    if answer_text is None:
        return None
    cleaned = re.sub(r"[^0-9A-Fa-fX]", "", str(answer_text))
    m = re.search(r'(X|[0-9A-Fa-f]{8})', cleaned)
    return m.group(1).upper() if m else None

def poll_pair(session: requests.Session, ip: str, pair: str, timeout: int, verbose: bool) -> Optional[str]:
    url = f"http://{ip}/cgi-bin/mkv.cgi"
    q = question_from_pair(pair)
    try:
        r = session.post(url, data={"QUESTION": q}, timeout=timeout)
        token = extract_token(r.text if r.status_code == 200 else None)
        log_qna(verbose, ip, pair, q, r.text if r is not None else None, token)
        return token  # 'X' or 8-hex or None
    except Exception as e:
        log_qna(verbose, ip, pair, q, f"EXC:{e}", None)
        return None

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

def slugify(s: str) -> str:
    return "".join(c.lower() if (c.isalnum() or c in "-_") else "_" for c in (s or ""))

def csv_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(",")] if s and s.strip() else []

def publish_discovery(cli: mqtt.Client, base_slug: str, name: str, discovery_prefix: str):
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
        conf_topic = f"{discovery_prefix}/{platform}/{base_slug}/{key}/config"
        state_topic = f"{base_slug}/{key}"
        payload: Dict[str, Any] = {
            "name": f"{name} {meta.get('name', key.replace('_',' ').title())}",
            "uniq_id": f"{base_slug}_{key}",
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

def worker(host_idx: int, ip: str, name: str, interval: int, timeout: int, verbose: bool,
           mqtt_settings: dict, scaling_overrides: Dict[str, float]):
    base_slug = slugify(name or ip)
    cli = mqtt.Client(client_id=f"mk5s_{base_slug}", clean_session=True)
    if mqtt_settings.get("user") or mqtt_settings.get("password"):
        cli.username_pw_set(mqtt_settings.get("user",""), mqtt_settings.get("password",""))
    avail_topic = f"{base_slug}/availability"
    cli.will_set(avail_topic, payload="offline", retain=True)
    cli.connect(mqtt_settings["host"], int(mqtt_settings["port"]), keepalive=60)

    publish_discovery(cli, base_slug, name, mqtt_settings["discovery_prefix"])
    cli.publish(avail_topic, "online", retain=True)

    session = requests.Session()

    while not stop_event.is_set():
        log_cycle_header(verbose, ip)
        # 1) Read every required pair individually to avoid misalignment
        pair_raw: Dict[str, Optional[str]] = {}
        for pair in PAIR_LIST:
            tok = poll_pair(session, ip, pair, timeout, verbose)
            pair_raw[pair] = None if tok in (None, 'X') else tok

        # 2) Decode & publish
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
                    # Optional multiplicative override (for edge variants)
                    if key in scaling_overrides and isinstance(calc, (int, float)):
                        try:
                            calc = calc * float(scaling_overrides[key])
                        except Exception:
                            pass
            # Publish
            state_topic = f"{base_slug}/{key}"
            cli.publish(state_topic, "unknown" if calc is None else str(calc), retain=True)
            # Verbose line per value
            log_value(verbose, ip, key, pair, meta["part"], raw8, partv, calc, meta.get("unit"))

        # Sleep with stop check
        for _ in range(int(interval * 10)):
            if stop_event.is_set():
                break
            time.sleep(0.1)

def main():
    try:
        with open(OPTIONS_PATH, "r") as f:
            opts = json.load(f)
    except Exception:
        opts = {}

    ip_list = csv_list(opts.get("ip_list", ""))
    name_list = csv_list(opts.get("name_list", ""))
    interval_list = csv_list(opts.get("interval_list", ""))
    timeout_list = csv_list(opts.get("timeout_list", ""))
    verbose_list = csv_list(opts.get("verbose_list", ""))

    # Optional per-sensor multiplicative overrides (e.g., {"module_hours": 1})
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

    threads: List[threading.Thread] = []
    for i, ip in enumerate(ip_list):
        name = pick(name_list, i, ip)
        try:
            interval = int(pick(interval_list, i, "10"))
        except Exception:
            interval = 10
        try:
            timeout = int(pick(timeout_list, i, "5"))
        except Exception:
            timeout = 5
        verbose = pick(verbose_list, i, "false").lower() in ("1","true","yes","on")

        print(f"[mk5s] starting: host={ip} name={name} interval={interval}s timeout={timeout} verbose={verbose}")
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
