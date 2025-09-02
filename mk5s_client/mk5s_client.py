#!/usr/bin/env python3
import os, time, requests, json, datetime, sys

HOST = os.getenv("MK5S_HOST", "10.60.23.11").strip()
SCAN_INTERVAL = int(os.getenv("MK5S_SCAN_INTERVAL", "15"))
REQ_TIMEOUT = int(os.getenv("MK5S_REQUEST_TIMEOUT", "5"))
LOG_RAW = os.getenv("MK5S_LOG_RAW", "true").lower() == "true"

SUPERVISOR_TOKEN = os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN")
CORE_API = "http://supervisor/core/api"

# Constant QUESTION string (baked in)
QUESTION_HEX = (
"30020130020330020530020830030130030230030a300701300703300704300705300706300707300708300709"
"30070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501"
"300502300504300505300507300508300509300e03300e04300e2a300e88311301311303311304311305311307"
"31130831130931130a31130b31130c31130d31130e31130f311310311311311312311313311314311315311316"
"31131731131831131931131a31131b31131c31131d31131e31131f311320311321311322311323311324311325"
"31132631132731132831132931132a31132b31132c31132d31132e31132f311330311331311332311333311334"
"31133531133631133731133831133931133a31133b31133c31133d31133e31133f311340311341311342311343"
"31134431134531134631134731134831134931134a31134b31134c31134d31134e31134f311350311351311352"
"31135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f311360311361"
"311362311363311364311365311366311367311401311402311403311404311405311406311407311408311409"
"31140a31140b31140c31140d31140e31140f311410311411311412300901300906300907300108"
)

# Parse QUESTION into pairs for decode map
def parse_question_pairs(qhex: str):
    pairs = []
    for i in range(0, len(qhex), 6):
        idx = int(qhex[i:i+4], 16)
        si  = int(qhex[i+4:i+6], 16)
        pairs.append((idx, si))
    return pairs

PAIRS = parse_question_pairs(QUESTION_HEX)

# Helpers to decode hex8 into pieces
def split_hex8(hex8: str):
    hi = int(hex8[0:4], 16)
    lo = int(hex8[4:8], 16)
    u32 = int(hex8, 16)
    return hi, lo, u32

# Publish a sensor to HA Core API
def publish_state(entity_id: str, state, attrs: dict):
    if not SUPERVISOR_TOKEN:
        print("[mk5s] missing SUPERVISOR_TOKEN; cannot publish states", flush=True)
        return
    url = f"{CORE_API}/states/{entity_id}"
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
    payload = {"state": state, "attributes": attrs}
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        if r.status_code >= 300:
            print(f"[mk5s] publish {entity_id} failed: {r.status_code} {r.text}", flush=True)
    except Exception as e:
        print(f"[mk5s] publish {entity_id} error: {e}", flush=True)

def fetch_answer():
    url = f"http://{HOST}/cgi-bin/mkv.cgi"
    data = {"QUESTION": QUESTION_HEX}
    r = requests.post(url, data=data, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.text.strip(), dict(r.headers)

def decode_answer(ans: str):
    """Decode the controller answer string against our PAIRS list into dict {(idx,si): hex8 or None}"""
    out = {}
    pos = 0
    for (idx, si) in PAIRS:
        if pos >= len(ans):
            out[(idx,si)] = None
            continue
        ch = ans[pos]
        if ch == 'X':
            out[(idx,si)] = None
            pos += 1
        else:
            # expect 8 hex chars
            val = ans[pos:pos+8]
            if len(val) < 8:
                out[(idx,si)] = None
                pos = len(ans)
            else:
                out[(idx,si)] = val
                pos += 8
    return out

def main_loop():
    print(f"[mk5s] polling {HOST} every {SCAN_INTERVAL}s (timeout {REQ_TIMEOUT}s)")
    while True:
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            ans, hdrs = fetch_answer()
            if LOG_RAW:
                print(f"[mk5s] {ts} QUESTION={QUESTION_HEX}")
                print(f"[mk5s] {ts} ANSWER={ans}")
            decoded = decode_answer(ans)

            # Extract confirmed-good fields
            # 1) Pressure bar from (3002,1) hiU16/1000
            p_hex = decoded.get((0x3002, 0x01))
            if p_hex:
                hi, lo, u32 = split_hex8(p_hex)
                pressure = round(hi / 1000.0, 3)
                publish_state(
                    "sensor.mk5s_pressure_bar",
                    pressure,
                    {
                        "friendly_name": "MK5S Druck",
                        "unit_of_measurement": "bar",
                        "device_class": "pressure",
                        "state_class": "measurement",
                        "raw_hex": p_hex,
                        "index": "0x3002/0x01",
                    },
                )

            # 2) Motorstarts from (3007,3) loU16
            ms_hex = decoded.get((0x3007, 0x03))
            if ms_hex:
                hi, lo, u32 = split_hex8(ms_hex)
                publish_state(
                    "sensor.mk5s_motorstarts",
                    lo,
                    {
                        "friendly_name": "MK5S Motorstarts",
                        "state_class": "total_increasing",
                        "raw_hex": ms_hex,
                        "index": "0x3007/0x03",
                    },
                )

            # 3) Lastspiele from (3007,4) loU16
            ls_hex = decoded.get((0x3007, 0x04))
            if ls_hex:
                hi, lo, u32 = split_hex8(ls_hex)
                publish_state(
                    "sensor.mk5s_lastspiele",
                    lo,
                    {
                        "friendly_name": "MK5S Lastspiele",
                        "state_class": "total_increasing",
                        "raw_hex": ls_hex,
                        "index": "0x3007/0x04",
                    },
                )

            # 4) Lüfterstarts from (3007,0x0B) UInt32
            fs_hex = decoded.get((0x3007, 0x0B))
            if fs_hex:
                hi, lo, u32 = split_hex8(fs_hex)
                publish_state(
                    "sensor.mk5s_luefterstarts",
                    u32,
                    {
                        "friendly_name": "MK5S Lüfterstarts",
                        "state_class": "total_increasing",
                        "raw_hex": fs_hex,
                        "index": "0x3007/0x0B",
                    },
                )

        except Exception as e:
            print(f"[mk5s] fetch error: {e}", flush=True)

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        sys.exit(0)
