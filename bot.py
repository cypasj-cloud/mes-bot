"""Paleidžia botą realiu laiku su tikrais (uždelstais) MES duomenimis.

    python bot.py          – tikri duomenys iš Yahoo
    python bot.py --sim    – simuliuota rinka (testui, veikia ir savaitgalį)
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import config
from data_feed import SimFeed, YahooFeed
from engine import Engine
from paper_broker import PaperBroker

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def write_status(engine: Engine):
    path = os.path.join(config.DATA_DIR, "status.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(engine.status(), f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="simuliuota rinka vietoje Yahoo")
    args = ap.parse_args()

    broker = PaperBroker()
    engine = Engine(broker)
    feed = SimFeed() if args.sim else YahooFeed()

    tf = config.LIVE.timeframe
    print(f"🐒 MES botas startavo. Balansas: ${broker.balance:,.2f}. "
          f"Šaltinis: {'simuliacija' if args.sim else 'Yahoo (~10 min vėlavimas)'}")
    print(f"Nustatymai: {config.LIVE.label()}")

    # įšildom EMA su istorija, kad nereikėtų laukti valandų
    history = feed.get_bars(100, tf) if args.sim else feed.get_bars("5d", tf)
    for bar in history:
        engine.on_bar(bar, warmup=True)
    last_time = history[-1].time if history else None
    print(f"Įšildyta su {len(history)} žvakėmis. Laukiu naujų...")

    while True:
        try:
            bars = feed.get_bars(1, tf) if args.sim else feed.get_bars("1d", tf)
            new = [b for b in bars if last_time is None or b.time > last_time]
            for bar in new:
                engine.on_bar(bar)
                last_time = bar.time
            if new:
                s = engine.status()
                pos = "FLAT" if not s["position"] else ("LONG" if s["position"]["dir"] > 0 else "SHORT")
                print(f"{datetime.now():%H:%M:%S}  MES {s['price']:.2f}  {pos}  "
                      f"atviras {s['open_pnl']:+.2f}$  balansas ${s['balance']:,.2f}")
            write_status(engine)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # tinklo klaidos neturi numušti boto
            print(f"⚠ Klaida: {e} – bandysiu vėl po {config.POLL_SECONDS}s")
        time.sleep(1 if args.sim else config.POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSustabdyta. Būsena išsaugota data/ aplanke.")
