"""Savaitės apžvalga – kaip beždžionės „mokosi“.

Kiekvieną šeštadienį išbando visas kandidatų strategijas su paskutinių ~60 dienų
tikrais MES duomenimis. Strategija gali būti pakeista TIK jei ji:
  * buvo pelninga ABIEJOSE laikotarpio pusėse (kad nebūtų atsitiktinė sėkmė),
  * turi profit factor ≥ 1.1 ir bent 20 sandorių,
  * ir yra geresnė už dabartinę.
Jei niekas neatitinka – lieka dabartinė strategija. Rezultatas: data/strategy.json.

    python review.py          – tikri duomenys
    python review.py --sim    – testas su simuliacija
"""
import argparse
import sys
from datetime import datetime, timezone

import backtest
import config
from run_once import STRATEGY, current_strategy, load_json, save_json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def score(s):
    ok = s["n"] >= 20 and s["pf"] >= 1.1 and s["h1"] > 0 and s["h2"] > 0
    return ok, s["total"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    args = ap.parse_args()

    data = backtest.load(args.sim)
    if not data[5]:
        print("Negavau duomenų – apžvalga atidėta.")
        return
    cur_name, _ = current_strategy()
    table = []
    for name, p in config.CANDIDATES.items():
        bars = data[p.timeframe]
        broker, _ = backtest.run(bars, p)
        s = backtest.stats(broker.trades, bars)
        ok, val = score(s)
        table.append({"name": name, "n": s["n"], "win": round(s["win"], 3),
                      "pf": None if s["pf"] == float("inf") else round(s["pf"], 2),
                      "total": round(s["total"], 2), "h1": round(s["h1"], 2), "h2": round(s["h2"], 2), "ok": ok})
        print(f"{name:<16} sand. {s['n']:>4}  PF {s['pf']:.2f}  P&L {s['total']:+8.0f}  "
              f"pusės {s['h1']:+.0f} / {s['h2']:+.0f}  {'✅' if ok else '—'}")

    good = sorted([r for r in table if r["ok"]], key=lambda r: r["total"], reverse=True)
    cur = next(r for r in table if r["name"] == cur_name)
    if good and good[0]["name"] != cur_name and (not cur["ok"] or good[0]["total"] > cur["total"]):
        new = good[0]["name"]
        lesson = f"Keičiam strategiją: {cur_name} → {new}. {new} buvo pelninga abiejose pusėse ({good[0]['total']:+.0f} $)."
    else:
        new = cur_name
        lesson = (f"Liekam prie {cur_name}." if cur["ok"] else
                  f"Liekam prie {cur_name}, nors ji testą išlaikė ne visai – geresnės kandidatės nėra.")
    print(lesson)
    save_json(STRATEGY, {"name": new, "chosen_at": datetime.now(timezone.utc).isoformat(),
                         "review": {"at": datetime.now(timezone.utc).isoformat(), "lesson": lesson, "table": table}})


if __name__ == "__main__":
    main()
