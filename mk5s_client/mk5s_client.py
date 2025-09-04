#!/usr/bin/env python3
import os, time, json, threading, requests, re
import socket
from typing import List, Dict, Tuple
import paho.mqtt.client as mqtt

DEFAULT_QUESTION = (
    # Only confirmed-good keys by default
    "300201"  # Kompressorauslass (bar, HiU16/1000)
    "300203"  # Elementauslass (°C, HiU16/10)
    "300205"  # Umgebungsluft (°C, HiU16/10)
    "300208"  # Controller Temperature (°C, HiU16/10)
    "300703"  # Motorstarts (LoU16)
    "300704"  # Lastspiele (LoU16)
    "30070B"  # Lüfterstarts (LoU16)
    "30070C"  # Erzeugte Druckluftmenge (LoU16*1000)
)

CONF_MAP = {
    "3002.01": {"name": "Kompressorauslass",       "unit": "bar", "decode": lambda hi, lo: round(hi/1000.0, 3), "device_class": "pressure", "state_class": "measurement"},
    "3002.03": {"name": "Elementauslass",         "unit": "°C",  "decode": lambda hi, lo: round(hi/10.0, 1),    "device_class": "temperature", "state_class": "measurement"},
    "3002.05": {"name": "Umgebungsluft",          "unit": "°C",  "decode": lambda hi, lo: round(hi/10.0, 1),    "device_class": "temperature", "state_class": "measurement"},
    "3002.08": {"name": "Controller Temperature", "unit": "°C",  "decode": lambda hi, lo: round(hi/10.0, 1),    "device_class": "temperature", "state_class": "measurement"},
    "3007.03": {"name": "Motorstarts",            "unit": None,  "decode": lambda hi, lo: lo,                   "state_class": "total_increasing"},
    "3007.04": {"name": "Lastspiele",             "unit": None,  "decode": lambda hi, lo: lo,                   "state_class": "total_increasing"},
    "3007.0B": {"name": "Lüfterstarts",           "unit": None,  "decode": lambda hi, lo: lo,                   "state_class": "total_increasing"},
    "3007.0C": {"name": "Erzeugte Druckluftmenge","unit": "m³",  "decode": lambda hi, lo: lo * 1000,            "device_class": "volume", "state_class": "total_increasing"},
}

HEX_RE = re.compile(r'^[0-9A-Fa-f]+$')

def split_csv(s: str) -> List[str]:
    s = (s or "").strip()
    if not s:
        return []
    return [x.strip() for x in s.split(",")]

def normalize_lists(primary: List[str], *others: List[str]) -> Tuple[List[str], ...]:
    n = len(primary) if primary else 0
    out = [primary]
    for lst in others:
        if not lst:
            out.append([""] * n)
        elif len(lst) == 1 and n > 1:
            out.append(lst * n)
        elif len(lst) < n:
            out.append((lst + [""] * n)[:n])
        else:
            out.append(lst[:n])
    return tuple(out)

def parse_question_keys(qhex: str) -> List[str]:
    q = re.sub(r'\s+', '', qhex or '')
    keys = []
    for i in range(0, len(q), 6):
        chunk = q[i:i+6]
        if len(chunk) < 6: break
        keys.append(f"{chunk[:4].upper()}.{chunk[4:6].upper()}")
    return keys

def parse_answer_words(ahex: str) -> List[int]:
    txt = (ahex or "").strip()
    # Some controllers may write extra text; keep only hex
    hex_only = re.sub(r'[^0-9A-Fa-f]', '', txt)
    words = []
    for i in range(0, len(hex_only), 8):
        w = hex_only[i:i+8]
        if len(w) < 8: break
        try:
            words.append(int(w, 16))
        except ValueError:
            break
    return words

def hi_lo_u16_from_u32(u: int) -> Tuple[int,int]:
    hi = (u >> 16) & 0xFFFF
    lo = u & 0xFFFF
    return hi, lo

def ensure_mqtt_client(host: str, port: int, username: str, password: str) -> mqtt.Client:
    client = mqtt.Client()
    if username:
        client.username_pw_set(username, password or "")
    # Don't block startup if broker is not ready yet: loop_start and reconnect on publish
    client.connect_async(host, port, 60)
    client.loop_start()
    return client

def publish_discovery(client: mqtt.Client, discovery_prefix: str, base: str, name: str, keys: List[str]):
    device = {
        "identifiers": [f"mk5s_{name}"],
        "manufacturer": "Atlas Copco",
        "model": "MK5S Touch",
        "name": name
    }
    for key in keys:
        if key not in CONF_MAP: 
            continue
        c = CONF_MAP[key]
        sensor_name = c["name"]
        uniq = f"{name}_{key.replace('.','_')}"
        state_topic = f"{base}/{key}/state"
        cfg = {
            "name": sensor_name,
            "unique_id": uniq,
            "state_topic": state_topic,
            "device": device,
            "force_update": False,
        }
        if "unit" in c and c["unit"]:
            cfg["unit_of_measurement"] = c["unit"]
        if "device_class" in c:
            cfg["device_class"] = c["device_class"]
        if "state_class" in c:
            cfg["state_class"] = c["state_class"]
        topic = f"{discovery_prefix}/sensor/{uniq}/config"
        client.publish(topic, json.dumps(cfg), qos=1, retain=True)

def decode_known(keys: List[str], words: List[int]) -> Dict[str, float]:
    out = {}
    for i, key in enumerate(keys):
        if i >= len(words): break
        if key in CONF_MAP:
            hi, lo = hi_lo_u16_from_u32(words[i])
            try:
                out[key] = CONF_MAP[key]["decode"](hi, lo)
            except Exception:
                pass
    return out

def try_post(host: str, qhex: str, timeout: int, verbose: bool) -> Tuple[str, Dict[str, List[str]]]:
    url = f"http://{host}/cgi-bin/mkv.cgi"
    headers = {"Connection": "close", "Content-Type": "text/plain"}
    # Method A: raw body
    try:
        r = requests.post(url, data=qhex, timeout=timeout, headers=headers)
        if verbose:
            print(f"[{host}] POST A status={r.status_code}")
        if r.ok and HEX_RE.match(re.sub(r'[^0-9A-Fa-f]', '', r.text) or ""):
            return r.text, {"hdr": [f"{k}: {v}" for k,v in r.headers.items()]}
    except Exception as e:
        if verbose: print(f"[{host}] POST A error: {e}")

    # Method B: form-encoded
    try:
        r = requests.post(url, data={"Q": qhex}, timeout=timeout)
        if verbose:
            print(f"[{host}] POST B status={r.status_code}")
        if r.ok:
            return r.text, {"hdr": [f"{k}: {v}" for k,v in r.headers.items()]}
        return r.text, {"hdr": [f"{k}: {v}" for k,v in r.headers.items()]}
    except Exception as e:
        if verbose: print(f"[{host}] POST B error: {e}")
        raise

def worker(cfg, mqttc):
    host = cfg["host"]
    name = cfg["name"]
    question = cfg["question"] or DEFAULT_QUESTION
    interval = int(cfg["interval"] or 10)
    timeout  = int(cfg["timeout"] or 5)
    verbose  = (str(cfg["verbose"]).lower() == "true")
    base_topic = f"mk5s/{name}"
    keys = parse_question_keys(question)

    # Publish discovery for known keys
    publish_discovery(mqttc, cfg["discovery_prefix"], base_topic, name, keys)

    while True:
        try:
            txt, meta = try_post(host, question, timeout, verbose)
            if verbose:
                print(f"[{host}] Question:\n{question}")
                print(f"[{host}] Answer:\n{txt[:512]}")
                for h in meta.get("hdr", []):
                    print(f"[{host}] H {h}")

            words = parse_answer_words(txt)
            decoded = decode_known(keys, words)

            # Publish individual sensor states
            for key, value in decoded.items():
                topic = f"{base_topic}/{key}/state"
                mqttc.publish(topic, str(value), qos=0, retain=False)

        except Exception as e:
            print(f"[{host}] poll error: {e}")
        time.sleep(interval)

def main():
    # Load options
    with open("/data/options.json", "r", encoding="utf-8") as f:
        opt = json.load(f)

    hosts     = split_csv(opt.get("hosts", ""))
    names     = split_csv(opt.get("names", "")) or [h.replace(".", "_") for h in hosts]
    intervals = split_csv(opt.get("intervals", "")) or ["10"]
    timeouts  = split_csv(opt.get("timeouts", ""))  or ["5"]
    verbose   = split_csv(opt.get("verbose", ""))   or ["false"]
    questions = split_csv(opt.get("questions", "")) # optional

    hosts, names, intervals, timeouts, verbose, questions = normalize_lists(
        hosts, names, intervals, timeouts, verbose, questions
    )

    mqtt_host = opt.get("mqtt_host", "localhost") or "localhost"
    mqtt_port = int(opt.get("mqtt_port", 1883) or 1883)
    mqtt_user = opt.get("mqtt_user", "") or ""
    mqtt_pass = opt.get("mqtt_password", "") or ""
    discovery_prefix = opt.get("discovery_prefix", "homeassistant") or "homeassistant"

    mqttc = ensure_mqtt_client(mqtt_host, mqtt_port, mqtt_user, mqtt_pass)

    threads = []
    for i, host in enumerate(hosts):
        if not host:
            continue
        cfg = dict(
            host=host, name=(names[i] or host.replace(".", "_")), 
            interval=intervals[i], timeout=timeouts[i], verbose=verbose[i],
            question=(questions[i] if i < len(questions) else ""),
            discovery_prefix=discovery_prefix
        )
        t = threading.Thread(target=worker, args=(cfg, mqttc), daemon=True)
        t.start()
        threads.append(t)
        print(f"[mk5s] worker started: host={cfg['host']} name={cfg['name']} interval={cfg['interval']}s")

    # Keep the main thread alive
    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
