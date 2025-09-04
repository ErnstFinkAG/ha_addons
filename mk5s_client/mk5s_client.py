#!/usr/bin/env python3
import os, json, threading, time, signal, sys, re
import requests
import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"

DEFAULT_QUESTION = "30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300907300108"

CONFIRMED_KEYS = {
    "pressure_bar": "3002.01",   # HiU16 / 1000
    "motor_starts": "3007.03",    # LoU16
    "load_cycles":  "3007.04",    # LoU16
}

stop_event = threading.Event()

def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "mk5s"

def parse_csv_list(s: str):
    if s is None:
        return []
    return [x.strip() for x in s.split(",")] if s.strip() else []

def build_question_pairs(question_hex: str):
    pairs = []
    for i in range(0, len(question_hex), 6):
        chunk = question_hex[i:i+6]
        if len(chunk) != 6:
            break
        idx = chunk[:4].upper()
        si  = chunk[4:6].upper()
        pairs.append(f"{idx}.{si}")
    return pairs

def parse_answer(answer_hex: str, pairs):
    out = {}
    ia = 0
    for key in pairs:
        if ia >= len(answer_hex):
            out[key] = None
            continue
        ch = answer_hex[ia]
        if ch == 'X':
            out[key] = None
            ia += 1
        else:
            if ia + 8 <= len(answer_hex):
                out[key] = answer_hex[ia:ia+8].upper()
                ia += 8
            else:
                out[key] = None
                ia = len(answer_hex)
    return out

def u16_hi(raw8: str):
    return int(raw8[0:4], 16)

def u16_lo(raw8: str):
    return int(raw8[4:8], 16)

def post_question(ip: str, question_hex: str, timeout: int):
    url = f"http://{ip}/cgi-bin/mkv.cgi"
    r = requests.post(url, data={"QUESTION": question_hex}, timeout=timeout)
    r.raise_for_status()
    return r.text.strip(), r.headers

def publish_discovery(cli: mqtt.Client, base_slug: str, name: str, disc_prefix: str):
    device = {
        "identifiers": [f"mk5s_{base_slug}"],
        "name": name,
        "manufacturer": "Atlas Copco",
        "model": "MK5s Touch",
    }
    base_topic = f"{base_slug}"
    avail_topic = f"{base_topic}/availability"
    sensors = [
        ("pressure_bar", "Pressure", "pressure_bar", "bar", "measurement", "pressure"),
        ("motor_starts", "Motor Starts", "motor_starts", None, "total_increasing", None),
        ("load_cycles",  "Load Cycles", "load_cycles", None, "total_increasing", None),
    ]
    for sensor_id, nice, state_key, unit, state_class, device_class in sensors:
        conf_topic = f"{disc_prefix}/sensor/{base_slug}/{sensor_id}/config"
        payload = {
            "name": f"{name} {nice}",
            "uniq_id": f"{base_slug}_{sensor_id}",
            "stat_t": f"{base_topic}/{state_key}",
            "avty_t": avail_topic,
            "dev": device,
            "qos": 0,
            "ret": True,
        }
        if unit:
            payload["unit_of_meas"] = unit
        if state_class:
            payload["stat_cla"] = state_class
        if device_class:
            payload["dev_cla"] = device_class
        cli.publish(conf_topic, json.dumps(payload), retain=True)

def worker(host_idx: int, ip: str, name: str, interval: int, timeout: int, verbose: bool,
           mqtt_settings: dict, question_hex: str):
    base_slug = slugify(name or ip)
    question_hex = (question_hex or DEFAULT_QUESTION).strip()
    pairs = build_question_pairs(question_hex)

    cli = mqtt.Client(client_id=f"mk5s_{base_slug}", clean_session=True)
    cli.username_pw_set(mqtt_settings["user"], mqtt_settings["password"])
    avail_topic = f"{base_slug}/availability"
    cli.will_set(avail_topic, payload="offline", retain=True)

    cli.connect(mqtt_settings["host"], int(mqtt_settings["port"]), keepalive=60)
    cli.loop_start()

    publish_discovery(cli, base_slug, name or ip, mqtt_settings["discovery_prefix"])
    cli.publish(avail_topic, "online", retain=True)

    while not stop_event.is_set():
        try:
            ans, hdrs = post_question(ip, question_hex, timeout)
            if verbose:
                print("Question:"); print(question_hex)
                print("Answer:"); print(ans)
            mapa = parse_answer(ans, pairs)
            def get_raw(key):
                kk = CONFIRMED_KEYS[key]
                return mapa.get(kk)
            raw_pressure = get_raw("pressure_bar")
            raw_ms = get_raw("motor_starts")
            raw_lc = get_raw("load_cycles")

            pressure_val = round(u16_hi(raw_pressure)/1000.0, 3) if raw_pressure else None
            ms_val = u16_lo(raw_ms) if raw_ms else None
            lc_val = u16_lo(raw_lc) if raw_lc else None

            if verbose:
                print(f"[values] {name}: pressure={pressure_val if pressure_val is not None else '—'} bar, motor_starts={ms_val if ms_val is not None else '—'}, load_cycles={lc_val if lc_val is not None else '—'}")

            if pressure_val is not None:
                cli.publish(f"{base_slug}/pressure_bar", str(pressure_val), retain=True)
            if ms_val is not None:
                cli.publish(f"{base_slug}/motor_starts", str(ms_val), retain=True)
            if lc_val is not None:
                cli.publish(f"{base_slug}/load_cycles", str(lc_val), retain=True)

            cli.publish(avail_topic, "online", retain=True)
        except Exception as e:
            print(f"[mk5s] poll error for {ip}: {e}", file=sys.stderr)
            try: cli.publish(avail_topic, "offline", retain=True)
            except Exception: pass

        for _ in range(int(interval*10)):
            if stop_event.is_set(): break
            time.sleep(0.1)

    try: cli.publish(avail_topic, "offline", retain=True)
    except Exception: pass
    cli.loop_stop()
    try: cli.disconnect()
    except Exception: pass

def main():
    if not os.path.exists(OPTIONS_PATH):
        print("[mk5s] options.json not found; using defaults for single host")
        opts = {}
    else:
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            opts = json.load(f)

    ip_list        = parse_csv_list(opts.get("ip_list", ""))
    name_list      = parse_csv_list(opts.get("name_list", ""))
    interval_list  = parse_csv_list(opts.get("interval_list", ""))
    timeout_list   = parse_csv_list(opts.get("timeout_list", ""))
    verbose_list   = parse_csv_list(opts.get("verbose_list", ""))
    question_list  = parse_csv_list(opts.get("question_list", ""))

    default_question = (opts.get("question") or DEFAULT_QUESTION).strip()

    if not ip_list:
        ip_list = ["10.60.23.11"]
    n = len(ip_list)

    def pick(lst, i, default):
        if not lst: return default
        return lst[i] if i < len(lst) and lst[i] != "" else (lst[-1] if lst[-1] != "" else default)

    mqtt_settings = {
        "host": opts.get("mqtt_host", "localhost"),
        "port": opts.get("mqtt_port", 1883),
        "user": opts.get("mqtt_user", "mqtt_user"),
        "password": opts.get("mqtt_password", "mqtt_password"),
        "discovery_prefix": opts.get("discovery_prefix", "homeassistant"),
    }

    threads = []
    for i in range(n):
        ip = ip_list[i]
        name = pick(name_list, i, ip)
        try: interval = int(pick(interval_list, i, "10"))
        except: interval = 10
        try: timeout = int(pick(timeout_list, i, "5"))
        except: timeout = 5
        verbose = pick(verbose_list, i, "false").lower() in ("1","true","yes","on")
        qh = pick(question_list, i, default_question) or default_question

        print(f"[mk5s] starting: host={ip} name={name} interval={interval}s timeout={timeout} verbose={verbose}")
        t = threading.Thread(target=worker, args=(i, ip, name, interval, timeout, verbose, mqtt_settings, qh), daemon=True)
        threads.append(t); t.start()

    def handle_sigterm(signum, frame): stop_event.set()
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        while not stop_event.is_set(): time.sleep(0.5)
    finally:
        stop_event.set()
        for t in threads: t.join(timeout=5.0)

if __name__ == "__main__":
    main()
