"""Vienas boto „žingsnis“ – jį kas 15 min paleidžia GitHub Actions.

1. Atkuria būseną (balansas, pozicija, dienos limitai, ko išmoko).
2. Parsisiunčia naujas MES žvakes ir apdoroja tik tas, kurių dar nematė.
3. Išsaugo būseną ir parašo docs/data/status.json – jį skaito beždžionių biuras.

Galima paleisti ir ranka:  python run_once.py        (tikri Yahoo duomenys)
                           python run_once.py --sim  (simuliacija testui)
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import config
import session
from data_feed import SimFeed, YahooFeed
from engine import Engine
from paper_broker import PaperBroker

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = config.DATA_DIR
OUT = os.path.join("docs", "data")
ENGINE_STATE = os.path.join(DATA, "engine.json")
STRATEGY = os.path.join(DATA, "strategy.json")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def current_strategy():
    s = load_json(STRATEGY, {})
    name = s.get("name")
    if name in config.CANDIDATES:
        return name, config.CANDIDATES[name]
    return "Grįžimas z≥3", config.LIVE


def read_trades():
    path = os.path.join(DATA, "trades.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("entry", "exit", "pnl"):
            r[k] = float(r[k])
    return rows


def ny_date(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(session.NY).strftime("%Y-%m-%d")


def write_status(engine: Engine, broker: PaperBroker, name: str, bars, now):
    trades = read_trades()
    days = defaultdict(lambda: {"pnl": 0.0, "n": 0})
    for t in trades:
        d = days[ny_date(t["close_time"])]
        d["pnl"] = round(d["pnl"] + t["pnl"], 2)
        d["n"] += 1
    eq, curve = config.START_BALANCE, [config.START_BALANCE]
    for t in trades:
        eq += t["pnl"]
        curve.append(round(eq, 2))

    st = engine.status()
    today = now.astimezone(session.NY).date()
    day_bars = [b for b in bars if b.time.astimezone(session.NY).date() == today]
    st.update({
        "updated_at": now.isoformat(),
        "market_open": not session.must_be_flat(now, engine.p),
        "strategy": name,
        "start_balance": config.START_BALANCE,
        "day_open": day_bars[0].open if day_bars else (bars[-1].close if bars else None),
        "bars": [{"t": b.time.isoformat(), "c": b.close} for b in bars[-80:]],
        "trades": trades[-60:],
        "days": days,
        "equity": curve[-300:],
        "review": load_json(STRATEGY, {}).get("review"),
    })
    save_json(os.path.join(OUT, "status.json"), st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--now", help="testams: apsimesti, kad dabar yra šis UTC laikas (ISO)")
    args = ap.parse_args()

    name, params = current_strategy()
    broker = PaperBroker(data_dir=DATA)
    engine = Engine(broker, params, log=print)
    st = load_json(ENGINE_STATE, {})
    engine.import_state(st)
    last = st.get("last_bar")

    if args.sim:
        feed = SimFeed(seed=st.get("sim_seed", 1), start=datetime.fromisoformat(st["sim_t"]) if st.get("sim_t") else None)
        feed.price = st.get("sim_price", feed.price)
        old_sim = st.get("sim_hist", [])
        new = feed.get_bars(3, params.timeframe)
        from data_feed import Bar
        hist = [Bar(datetime.fromisoformat(h[0]), h[1], h[2], h[3], h[4]) for h in old_sim]
        bars = (hist + new)[-400:]
        st_sim = {"sim_seed": st.get("sim_seed", 1) + 1, "sim_t": feed.t.isoformat(), "sim_price": feed.price,
                  "sim_hist": [[b.time.isoformat(), b.open, b.high, b.low, b.close] for b in bars]}
    else:
        bars = YahooFeed().get_bars("5d", params.timeframe)
        st_sim = {}
    if not bars:
        print("Negavau duomenų – bandysiu kitą kartą.")
        return

    now = datetime.fromisoformat(args.now) if args.now else (bars[-1].time + timedelta(minutes=params.timeframe) if args.sim else datetime.now(timezone.utc))
    old = [b for b in bars if last and b.time.isoformat() <= last]
    new = [b for b in bars if last and b.time.isoformat() > last]
    if last is None:   # pirmas paleidimas: tik įšildom, praeities neprekiaujam
        old, new = bars, []
        print(f"Pirmas paleidimas: įšildyta su {len(old)} žvakėmis. Strategija: {name}")

    for b in old:
        engine.on_bar(b, warmup=True)
    for b in new:
        engine.on_bar(b)

    # jei pražiopsojom žvakes, o sesija jau baigėsi – vis tiek uždarom poziciją
    if broker.position and session.must_be_flat(now, params):
        tr = broker.close(bars[-1].close, now.isoformat(), "sesijos pabaiga")
        engine._after_close(tr)
        broker.save({"weights": engine.weights})

    save_json(ENGINE_STATE, {**engine.export_state(), "last_bar": bars[-1].time.isoformat(), **st_sim})
    write_status(engine, broker, name, bars, now)
    s = engine.status()
    pos = "FLAT" if not s["position"] else ("LONG" if s["position"]["dir"] > 0 else "SHORT")
    print(f"{now:%Y-%m-%d %H:%M} UTC | naujų žvakių {len(new)} | MES {s['price']:.2f} | {pos} | "
          f"balansas ${s['balance']:,.2f} | strategija {name}")


if __name__ == "__main__":
    main()
