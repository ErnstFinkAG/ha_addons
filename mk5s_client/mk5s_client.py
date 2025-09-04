#!/usr/bin/env python3
import argparse
import sys
import time
import requests

QUESTION = (
    "30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b"
    "30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504"
    "300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a"
    "31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a"
    "31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a"
    "31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a"
    "31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a"
    "31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a"
    "31135b31135c31135d31135e31135f311360311361311362311363311364311365311366311367311401311402311403"
    "31140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901"
    "300906300907300108"
)

def chunk_pairs(q_hex):
    # Each pair is 6 hex chars: index(4) + sub(2)
    return [q_hex[i:i+6] for i in range(0, len(q_hex), 6)]

def parse_answer(answer, pairs):
    i = 0
    out = {}
    for p in pairs:
        if i >= len(answer):
            out[p] = None
            continue
        c = answer[i]
        if c == 'X':
            out[p] = None
            i += 1
        else:
            if i + 8 <= len(answer):
                out[p] = answer[i:i+8]
                i += 8
            else:
                out[p] = None
                i = len(answer)
    return out

def u16_hi(hex8): return int(hex8[0:4], 16)
def u16_lo(hex8): return int(hex8[4:8], 16)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=5)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    url = f"http://{args.host}/cgi-bin/mkv.cgi"
    pairs = chunk_pairs(QUESTION)

    session = requests.Session()

    while True:
        try:
            if args.verbose:
                print("Question:")
                print(QUESTION, flush=True)
            resp = session.post(url, data={"QUESTION": QUESTION}, timeout=args.timeout)
            answer = (resp.text or "").strip()
            if args.verbose:
                print("Answer:")
                print(answer, flush=True)
                # Show headers
                print("RespHdr:")
                for k, v in resp.headers.items():
                    print(f"  {k}: {v}")
            # Parse the stream
            data_map = parse_answer(answer, pairs)

            # Confirmed-good fields
            # 3002.01 => pressure bar = HiU16 / 1000
            # 3007.03 => motor starts = LoU16
            # 3007.04 => load cycles  = LoU16
            p_word = data_map.get("300201")
            ms_word = data_map.get("300703")
            ls_word = data_map.get("300704")

            bar = None
            if p_word:
                bar = u16_hi(p_word) / 1000.0

            motor_starts = None
            if ms_word:
                motor_starts = u16_lo(ms_word)

            load_cycles = None
            if ls_word:
                load_cycles = u16_lo(ls_word)

            print("\n=== Summary (confirmed-good) ===")
            print(f"Kompressorauslass (bar) : {bar:.3f}" if bar is not None else "Kompressorauslass (bar) : —")
            print(f"Motorstarts             : {motor_starts if motor_starts is not None else '—'}")
            print(f"Lastspiele              : {load_cycles if load_cycles is not None else '—'}")
            sys.stdout.flush()

        except Exception as e:
            print(f"[mk5s] poll error: {e}", flush=True)

        time.sleep(max(1, args.interval))

if __name__ == "__main__":
    main()
