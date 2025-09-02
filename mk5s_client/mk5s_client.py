#!/usr/bin/env python3
import os, time, argparse, requests, json

SUP_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
HA_API = "http://supervisor/core/api"

def post_question(host: str, question: str, timeout=5):
    url = f"http://{host}/cgi-bin/mkv.cgi"
    data = {"QUESTION": question}
    r = requests.post(url, data=data, timeout=timeout)
    r.raise_for_status()
    return r.text.strip()

def parse_answer(question: str, answer: str):
    # Build item list in the order of the QUESTION
    items = [(question[i:i+4], question[i+4:i+6]) for i in range(0, len(question), 6)]
    res = {}
    pos = 0
    for idx, (ih, sh) in enumerate(items):
        key = f"{ih}.{sh}"
        if pos >= len(answer):
            res[key] = None
            continue
        ch = answer[pos]
        if ch == 'X':
            res[key] = None
            pos += 1
        else:
            if pos + 8 <= len(answer):
                res[key] = answer[pos:pos+8]
                pos += 8
            else:
                res[key] = None
                pos = len(answer)
    return res

def u16_hi(hex8): 
    return int(hex8[:4],16)
def u16_lo(hex8): 
    return int(hex8[4:],16)
def u32(hex8):
    return int(hex8,16)

def publish_state(entity_id, state, attrs):
    if SUP_TOKEN is None:
        print("[mk5s] WARNING: no SUPERVISOR_TOKEN, skipping publish")
        return
    url = f"{HA_API}/states/{entity_id}"
    headers = {"Authorization": f"Bearer {SUP_TOKEN}", "Content-Type": "application/json"}
    payload = {"state": state, "attributes": attrs}
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
    # Keep noisy logs down; print only errors
    if r.status_code >= 300:
        print(f"[mk5s] publish {entity_id} failed: {r.status_code} {r.text}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--interval", type=int, default=10)
    args = ap.parse_args()

    q = args.question.strip()
    while True:
        try:
            ans = post_question(args.host, q, timeout=5)
            print(f"Question:\n{q}\nAnswer:\n{ans}\n", flush=True)

            parsed = parse_answer(q, ans)

            # Confirmed-good mappings
            # 1) Pressure (bar): 3002/01 -> HiU16 / 1000
            p_hex = parsed.get("3002.01")
            if p_hex:
                p_bar = round(u16_hi(p_hex) / 1000.0, 3)
                publish_state(
                    "sensor.mk5s_pressure_bar",
                    p_bar,
                    {
                        "unit_of_measurement": "bar",
                        "friendly_name": "MK5S Pressure",
                        "device_class": "pressure",
                        "state_class": "measurement",
                        "raw_hex": p_hex,
                        "index": "3002.01"
                    }
                )
            else:
                publish_state("sensor.mk5s_pressure_bar", "unavailable",
                              {"unit_of_measurement":"bar","friendly_name":"MK5S Pressure","device_class":"pressure","state_class":"measurement"})

            # 2) Motorstarts: 3007/03 -> LoU16
            ms_hex = parsed.get("3007.03")
            if ms_hex:
                ms = u16_lo(ms_hex)
                publish_state(
                    "sensor.mk5s_motorstarts",
                    ms,
                    {
                        "friendly_name": "MK5S Motorstarts",
                        "state_class": "total_increasing",
                        "raw_hex": ms_hex,
                        "index": "3007.03"
                    }
                )
            else:
                publish_state("sensor.mk5s_motorstarts", "unavailable",
                              {"friendly_name":"MK5S Motorstarts","state_class":"total_increasing"})

            # 3) Lastspiele: 3007/04 -> LoU16
            ls_hex = parsed.get("3007.04")
            if ls_hex:
                ls = u16_lo(ls_hex)
                publish_state(
                    "sensor.mk5s_lastspiele",
                    ls,
                    {
                        "friendly_name": "MK5S Lastspiele",
                        "state_class": "total_increasing",
                        "raw_hex": ls_hex,
                        "index": "3007.04"
                    }
                )
            else:
                publish_state("sensor.mk5s_lastspiele", "unavailable",
                              {"friendly_name":"MK5S Lastspiele","state_class":"total_increasing"})

            # 4) Lüfterstarts: 3007/0B -> UInt32
            fs_hex = parsed.get("3007.0B")
            if fs_hex:
                fs = u32(fs_hex)
                publish_state(
                    "sensor.mk5s_luefterstarts",
                    fs,
                    {
                        "friendly_name": "MK5S Lüfterstarts",
                        "state_class": "total_increasing",
                        "raw_hex": fs_hex,
                        "index": "3007.0B"
                    }
                )
            else:
                publish_state("sensor.mk5s_luefterstarts", "unavailable",
                              {"friendly_name":"MK5S Lüfterstarts","state_class":"total_increasing"})

        except Exception as e:
            print(f"[mk5s] poll error: {e}", flush=True)

        time.sleep(max(1, int(args.interval)))

if __name__ == "__main__":
    main()
