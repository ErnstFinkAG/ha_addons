#!/usr/bin/env python3
# MK5s Client — Home Assistant add-on
# VERSION: 0.7.0-working-3007-multipass-2025-09-04

import os, json, threading, time, signal, re, hashlib
from typing import Dict, Any, List, Optional, Tuple
import requests
import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"
SELF_PATH = __file__
VERSION = "0.7.0-working-3007-multipass-2025-09-04"

def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# ------------------------- Verbose logging helpers ----------------------------
def vlog(enabled: bool, msg: str) -> None:
    if enabled:
        print(msg, flush=True)

def log_banner() -> None:
    sha = "unknown"
    try:
        sha = file_sha256(SELF_PATH)[:16]
    except Exception:
        pass
    print(f"[mk5s] mk5s_client.py VERSION={VERSION} SHA256[:16]={sha}", flush=True)

def log_cycle_header(enabled: bool, ip: str) -> None:
    vlog(enabled, f"[mk5s:{ip}] ==== decode cycle @ {time.strftime('%Y-%m-%d %H:%M:%S')} ====")

def log_group_qna(enabled: bool, ip: str, index: str, question_hex: str, answer: Optional[str], cleaned: Optional[str], tokens: List[Optional[str]]) -> None:
    if not enabled:
        return
    vlog(True, f"[mk5s:{ip}] Q[{index}]={question_hex}")
    vlog(True, f"[mk5s:{ip}] A[{index}]_RAW={repr(answer)}")
    clen = len(cleaned) if cleaned else 0
    vlog(True, f"[mk5s:{ip}] A[{index}]_CLEAN(len={clen})={repr(cleaned)} TOKENS={len(tokens)}")

def log_pair_token(enabled: bool, ip: str, pair: str, token: Optional[str], source: str) -> None:
    if not enabled:
        return
    tok = token if token is not None else "None"
    vlog(True, f"[mk5s:{ip}]   token[{source}] {pair} = {tok}")

def log_value(enabled: bool, ip: str, key: str, pair: str, part: str, raw8: Optional[str], partv: Optional[int], calc: Optional[Any], unit: Optional[str]) -> None:
    if not enabled:
        return
    raw_disp = raw8 if raw8 is not None else "X/None"
    part_disp = str(partv) if partv is not None else "—"
    calc_disp = "unknown" if calc is None else f"{calc}{unit or ''}"
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

# Group pairs by 4-hex index
INDEX_GROUPS: Dict[str, List[str]] = {}
for meta in SENSORS.values():
    pair = meta["pair"].upper()
    idx, sub = pair.split(".")
    INDEX_GROUPS.setdefault(idx, []).append(pair)
for idx in INDEX_GROUPS:
    INDEX_GROUPS[idx] = sorted(INDEX_GROUPS[idx], key=lambda p: int(p.split(".")[1], 16))

# Special multi-pass strategy for 3007.*
def permute_3007_order(pairs: List[str]) -> List[List[str]]:
    # default ascending
    p_default = list(pairs)
    # put 0D right after 01 (before 0B/0C)
    p_better = list(pairs)
    if "3007.01" in p_better and "3007.0D" in p_better:
        p_better.remove("3007.0D")
        ins_at = p_better.index("3007.01") + 1
        p_better.insert(ins_at, "3007.0D")
    # only 0D
    p_only = ["3007.0D"]
    # put 0B/0C after 0D
    p_after = list(pairs)
    for tgt in ["3007.0B","3007.0C"]:
        if tgt in p_after:
            p_after.remove(tgt)
    if "3007.0D" in p_after:
        idx = p_after.index("3007.0D") + 1
    else:
        idx = 0
    for tgt in ["3007.0B","3007.0C"]:
        if tgt in pairs:
            p_after.insert(idx, tgt)
            idx += 1
    # unique, keep order
    seen = set()
    out = []
    for lst in [p_default, p_better, p_only, p_after]:
        key = tuple(lst)
        if key not in seen:
            out.append(lst)
            seen.add(key)
    return out

# ------------------------------ HTTP helpers ---------------------------------
def clean_answer(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return re.sub(r'[^0-9A-Fa-fX]', '', s)

def tokenize_answer(cleaned: Optional[str], expected_tokens: int) -> List[Optional[str]]:
    tokens: List[Optional[str]] = []
    if not cleaned:
        return tokens
    i = 0
    n = len(cleaned)
    while i < n and len(tokens) < expected_tokens:
        ch = cleaned[i]
        if ch in ('X', 'x'):
            tokens.append('X')
            i += 1
        else:
            if i + 8 <= n and re.fullmatch(r'[0-9A-Fa-f]{8}', cleaned[i:i+8]):
                tokens.append(cleaned[i:i+8].upper())
                i += 8
            else:
                i += 1  # resync
    return tokens

def build_question(subs: List[str]) -> str:
    return "".join(p.replace(".","") for p in subs)

def http_post(session: requests.Session, ip: str, q: str, timeout: int) -> Tuple[Optional[str], Optional[str]]:
    url = f"http://{ip}/cgi-bin/mkv.cgi"
    try:
        r = session.post(url, data={"QUESTION": q}, timeout=timeout)
        raw = r.text if r.status_code == 200 else None
    except Exception as e:
        raw = f"EXC:{e}"
    cleaned = clean_answer(raw)
    return raw, cleaned

def poll_group(session: requests.Session, ip: str, idx: str, pairs: List[str], timeout: int, verbose: bool) -> Dict[str, Optional[str]]:
    q = build_question(pairs)
    raw, cleaned = http_post(session, ip, q, timeout)
    tokens = tokenize_answer(cleaned, expected_tokens=len(pairs))
    log_group_qna(verbose, ip, idx, q, raw, cleaned, tokens)
    out: Dict[str, Optional[str]] = {}
    for p, tok in zip(pairs, tokens):
        out[p] = None if tok in (None, 'X') else tok
        log_pair_token(verbose, ip, p, out[p] if tok not in (None,'X') else tok, source=f"group:{idx}")
    if len(tokens) < len(pairs):
        for p in pairs[len(tokens):]:
            out[p] = None
            log_pair_token(verbose, ip, p, None, source=f"group:{idx}:short")
    return out

def poll_pair(session: requests.Session, ip: str, pair: str, timeout: int, verbose: bool) -> Optional[str]:
    q = build_question([pair])
    raw, cleaned = http_post(session, ip, q, timeout)
    tokens = tokenize_answer(cleaned, expected_tokens=1)
    tok = tokens[0] if tokens else None
    log_pair_token(verbose, ip, pair, None if tok in (None,'X') else tok, source="fallback")
    return None if tok in (None,'X') else tok

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

def plausible_module_seconds(v_hex: Optional[str], alt_hex: Optional[str]) -> bool:
    if not v_hex or len(v_hex) != 8 or v_hex.upper() == "XXXXXXXX":
        return False
    try:
        v = int(v_hex, 16)
    except Exception:
        return False
    # Must be > ~1000 seconds and < 10 years (in seconds)
    return (v > 1000) and (v < 10 * 365 * 24 * 3600) and (v_hex != (alt_hex or ""))

def choose_best_3007(pass_maps: List[Dict[str, Optional[str]]]) -> Dict[str, Optional[str]]:
    # prefer a pass where 0D is plausible and != 14
    best = pass_maps[0]
    score_best = -1
    for m in pass_maps:
        v0d = m.get("3007.0D")
        v14 = m.get("3007.14")
        score = 0
        if v0d and v0d != "X":
            try:
                iv = int(v0d, 16)
                if iv > 1000:
                    score += 2
                if iv > 1000000:  # ~277h
                    score += 2
            except Exception:
                pass
        if v0d and v14 and v0d != v14:
            score += 2
        # fan_starts/acc_vol non-X help too
        if m.get("3007.0B") not in (None, "X"):
            score += 1
        if m.get("3007.0C") not in (None, "X"):
            score += 1
        if score > score_best:
            best = m
            score_best = score
    return best

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

        # --- PRIME READ --- (stabilize pages)
        try:
            prime_pairs = ["3003.01", "3003.02", "3003.0A", "3009.01"]
            q_prime = build_question(prime_pairs)
            raw_p, cleaned_p = http_post(session, ip, q_prime, timeout)
            if verbose:
                print(f"[mk5s:{ip}] PRIME_Q={q_prime}", flush=True)
                print(f"[mk5s:{ip}] PRIME_A_RAW={repr(raw_p)}", flush=True)
                print(f"[mk5s:{ip}] PRIME_A_CLEAN={repr(cleaned_p)}", flush=True)
        except Exception as e:
            if verbose:
                print(f"[mk5s:{ip}] PRIME_EXC={e}", flush=True)

        pair_raw: Dict[str, Optional[str]] = {}

        # Normal groups except 3007
        for idx, pairs in INDEX_GROUPS.items():
            if idx == "3007":
                continue
            gmap = poll_group(session, ip, idx, pairs, timeout, verbose)
            pair_raw.update(gmap)

        # 3007 multi-pass
        pairs_3007 = INDEX_GROUPS.get("3007", [])
        pass_maps: List[Dict[str, Optional[str]]] = []
        for order in permute_3007_order(pairs_3007):
            gmap = poll_group(session, ip, "3007", order, timeout, verbose)
            pass_maps.append(gmap)
        # Deep-read fallback for 0D if still implausible
        best = choose_best_3007(pass_maps)
        if not plausible_module_seconds(best.get("3007.0D"), best.get("3007.14")):
            tok = poll_pair(session, ip, "3007.0D", timeout, verbose)
            if tok is not None:
                best["3007.0D"] = tok
                log_pair_token(verbose, ip, "3007.0D", tok, source="deep")

        pair_raw.update(best)

        # Per-pair fallback for any remaining None
        for pair, tok in list(pair_raw.items()):
            if tok is None:
                tok2 = poll_pair(session, ip, pair, timeout, verbose)
                if tok2 is not None:
                    pair_raw[pair] = tok2

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
            log_value(verbose, ip, key, pair, meta["part"], raw8, partv, calc, meta.get("unit"))

        # Sleep
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
