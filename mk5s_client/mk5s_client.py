\
import argparse, time, json, sys, datetime as dt
import requests

QUESTION = ("30020130020330020530020830030130030230030a300701300703300704300705300706"
            "30070730070830070930070b30070c30070d30070e30070f300714300715300718300722"
            "30072330072430210130210530210a300501300502300504300505300507300508300509"
            "300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a"
            "31130b31130c31130d31130e31130f311310311311311312311313311314311315311316"
            "31131731131831131931131a31131b31131c31131d31131e31131f311320311321311322"
            "31132331132431132531132631132731132831132931132a31132b31132c31132d31132e"
            "31132f31133031133131133231133331133431133531133631133731133831133931133a"
            "31133b31133c31133d31133e31133f311340311341311342311343311344311345311346"
            "31134731134831134931134a31134b31134c31134d31134e31134f311350311351311352"
            "31135331135431135531135631135731135831135931135a31135b31135c31135d31135e"
            "31135f311360311361311362311363311364311365311366311367311401311402311403"
            "31140431140531140631140731140831140931140a31140b31140c31140d31140e31140f"
            "311410311411311412300901300906300907300108")

def post(host, question, timeout):
    url = f"http://{host}/cgi-bin/mkv.cgi"
    data = {"QUESTION": question}
    r = requests.post(url, data=data, timeout=timeout)
    r.raise_for_status()
    return r.text.strip(), r.headers

def split_u32(hex8):
    hi = int(hex8[0:4], 16)
    lo = int(hex8[4:8], 16)
    return hi, lo

def try_decode(answer):
    # We only care about the first 4 asked items for confirmed-good:
    # 0: 3002/01 -> pressure hiU16/1000
    # 1: 3007/01 -> composite U32, but we only confirm counters out of 03/04/0B
    # 2: 3007/03 -> motorstarts (LoU16)
    # 3: 3007/04 -> lastspiele  (LoU16)
    # 10: 3007/0B -> fan starts (UInt32)
    # The answer is a concatenation of 8-hex or 'X' per question, in order.
    # We map indices quickly to extract 0,2,3,10.
    values = {"pressure_bar": None, "motorstarts": None, "lastspiele": None, "luefterstarts": None}
    i = 0
    # Parse sequentially
    blocks = []
    idx = 0
    while idx < len(QUESTION):
        idx += 6  # 4 hex index + 2 hex subindex
        if i >= len(answer):
            break
        c = answer[i]
        if c == 'X':
            blocks.append(None)
            i += 1
        else:
            blocks.append(answer[i:i+8])
            i += 8
    # Extract positions if present
    try:
        h = blocks[0]
        if h:
            hi, lo = split_u32(h)
            values["pressure_bar"] = round(hi/1000.0, 3)
    except Exception:
        pass
    try:
        h = blocks[2]
        if h:
            _, lo = split_u32(h)
            values["motorstarts"] = lo
    except Exception:
        pass
    try:
        h = blocks[3]
        if h:
            _, lo = split_u32(h)
            values["lastspiele"] = lo
    except Exception:
        pass
    try:
        # Position 10: count from start
        h = blocks[10] if len(blocks) > 10 else None
        if h:
            values["luefterstarts"] = int(h, 16)
    except Exception:
        pass
    return values

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=5)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    while True:
        try:
            ans, hdrs = post(args.host, QUESTION, args.timeout)
            if args.verbose:
                print("Question:")
                print(QUESTION, flush=True)
                print("Answer:")
                print(ans, flush=True)
            vals = try_decode(ans)
            stamp = dt.datetime.utcnow().isoformat() + "Z"
            print(f"[mk5s] VALUES @ {stamp}: "
                  f"pressure_bar={vals.get('pressure_bar')}  "
                  f"motorstarts={vals.get('motorstarts')}  "
                  f"lastspiele={vals.get('lastspiele')}  "
                  f"luefterstarts={vals.get('luefterstarts')}", flush=True)
            # persist last values for debugging
            with open("/data/last_values.json","w",encoding="utf-8") as f:
                json.dump({"ts": stamp, "values": vals, "answer": ans}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[mk5s] poll error: {e}", file=sys.stderr, flush=True)
        time.sleep(max(1, args.interval))

if __name__ == "__main__":
    main()
