#!/usr/bin/env python3
import os, time, json, argparse, requests
from datetime import datetime

# ---- Constants ----
QUESTION_HEX = "30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300907300108"

PAIR_PRESSURE = (0x3002, 0x01)   # bar (HiU16 / 1000)
PAIR_MOTORSTARTS = (0x3007, 0x03) # LoU16
PAIR_LASTSPIELE  = (0x3007, 0x04) # LoU16
PAIR_FANSTARTS   = (0x3007, 0x0B) # UInt32

HA_API_BASE = "http://supervisor/core/api"
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN")

SENSORS = {
    "sensor.mk5s_pressure_bar": {
        "name": "MK5S Pressure",
        "unit": "bar",
        "device_class": "pressure"
    },
    "sensor.mk5s_motorstarts": {
        "name": "MK5S Motorstarts",
        "unit": None,
        "device_class": None
    },
    "sensor.mk5s_lastspiele": {
        "name": "MK5S Lastspiele",
        "unit": None,
        "device_class": None
    },
    "sensor.mk5s_luefterstarts": {
        "name": "MK5S Lüfterstarts",
        "unit": None,
        "device_class": None
    },
}

# ---- Helpers ----
def parse_pairs(hex_str):
    return [(int(hex_str[i:i+4], 16), int(hex_str[i+4:i+6], 16))
            for i in range(0, len(hex_str), 6)]

def parse_payload(pairs, payload):
    """Return mapping {(idx,sub): hex8 or None}"""
    out = {}
    i = 0
    for pair in pairs:
        if i >= len(payload):
            out[pair] = None
            continue
        c = payload[i]
        if c == 'X':
            out[pair] = None
            i += 1
        else:
            chunk = payload[i:i+8]
            if len(chunk) < 8:
                out[pair] = None
                i = len(payload)
            else:
                out[pair] = chunk.upper()
                i += 8
    return out

def u32(hex8): return int(hex8, 16)
def hi_u16(hex8): return int(hex8[0:4], 16)
def lo_u16(hex8): return int(hex8[4:8], 16)

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

def post_state(entity_id, state, attrs=None):
    if not HA_TOKEN:
        print("[mk5s] WARN: no SUPERVISOR_TOKEN; skipping HA state update")
        return
    url = f"{HA_API_BASE}/states/{entity_id}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }
    body = {"state": str(state), "attributes": {"friendly_name": SENSORS[entity_id]["name"]}}
    if SENSORS[entity_id]["unit"]:
        body["attributes"]["unit_of_measurement"] = SENSORS[entity_id]["unit"]
    if SENSORS[entity_id]["device_class"]:
        body["attributes"]["device_class"] = SENSORS[entity_id]["device_class"]
    if attrs:
        body["attributes"].update(attrs)
    try:
        r = requests.post(url, headers=headers, json=body, timeout=5)
        if r.status_code >= 300:
            print(f"[mk5s] HA state POST {entity_id} failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[mk5s] HA state POST {entity_id} error: {e}")

# ---- Main poll loop ----
def poll(host, timeout, verbose):
    url = f"http://{host}/cgi-bin/mkv.cgi"
    pairs = parse_pairs(QUESTION_HEX)
    try:
        resp = requests.post(url, data={"QUESTION": QUESTION_HEX}, timeout=timeout)
        payload = resp.text.strip()
        if verbose:
            print("Question:")
            print(QUESTION_HEX)
            print("Answer:")
            print(payload)
        data = parse_payload(pairs, payload)
        # Extract values
        p_hex = data.get(PAIR_PRESSURE)
        ms_hex = data.get(PAIR_MOTORSTARTS)
        ls_hex = data.get(PAIR_LASTSPIELE)
        fs_hex = data.get(PAIR_FANSTARTS)

        pressure_bar = round(hi_u16(p_hex)/1000.0, 3) if p_hex else None
        motorstarts = lo_u16(ms_hex) if ms_hex else None
        lastspiele  = lo_u16(ls_hex) if ls_hex else None
        fanstarts   = u32(fs_hex)    if fs_hex else None

        # Log values block
        print("[mk5s] VALUES @ {}: pressure_bar={}  motorstarts={}  lastspiele={}  luefterstarts={}".format(
            now(),
            ("{:.3f}".format(pressure_bar) if pressure_bar is not None else "—"),
            (motorstarts if motorstarts is not None else "—"),
            (lastspiele if lastspiele is not None else "—"),
            (fanstarts if fanstarts is not None else "—")
        ))

        # Publish to HA
        if pressure_bar is not None:
            post_state("sensor.mk5s_pressure_bar", pressure_bar)
        if motorstarts is not None:
            post_state("sensor.mk5s_motorstarts", motorstarts)
        if lastspiele is not None:
            post_state("sensor.mk5s_lastspiele", lastspiele)
        if fanstarts is not None:
            post_state("sensor.mk5s_luefterstarts", fanstarts)

    except Exception as e:
        print(f"[mk5s] poll error: {e}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=5)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    while True:
        poll(args.host, args.timeout, args.verbose)
        time.sleep(max(1, args.interval))

if __name__ == "__main__":
    main()
