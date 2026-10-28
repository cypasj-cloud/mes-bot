"""Savaitės apžvalga – kaip beždžionės „mokosi“.

Kiekvieną šeštadienį visos kandidatės strategijos išbandomos su ilga tikra MES istorija
(Databento ~5 mėn., arba Yahoo 60 d., jei Databento rakto nėra). Istorija dalijama į dvi dalis:

  * MOKYMASIS – viskas iki paskutinių 30 dienų. Čia strategija turi būti pelninga
    abiejose pusėse, turėti profit factor ≥ 1.1 ir bent 20 sandorių.
  * EGZAMINAS – paskutinės 30 dienų, kurių pasirinkimas „nemato“. Čia strategija
    turi būti pliuse, kitaip laikoma, kad ji tik „iškalė“ praeitį (overfitting).

Strategija keičiama tik į tokią, kuri išlaikė abu. Rezultatas: data/strategy.json.

    python review.py          – tikri duomenys
    python review.py --sim    – testas su simuliacija
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

import backtest
import config
from run_once import STRATEGY, current_strategy, save_json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXAM_DAYS = 30


def evaluate(bars, p):
    broker, _ = backtest.run(bars, p)
    tr = broker.trades
    exam_start = (bars[-1].time - timedelta(days=EXAM_DAYS)).isoformat()
    train = [t for t in tr if t["close_time"] < exam_start]
    exam = [t for t in tr if t["close_time"] >= exam_start]
    tb = [b for b in bars if b.time.isoformat() < exam_start] or bars
    s = backtest.stats(train, tb)
    exam_pnl = sum(t["pnl"] for t in exam)
    train_ok = s["n"] >= 20 and s["pf"] >= 1.1 and s["h1"] > 0 and s["h2"] > 0
    ok = train_ok and exam_pnl > 0
    return {"n": s["n"], "win": round(s["win"], 3),
            "pf": None if s["pf"] == float("inf") else round(s["pf"], 2),
            "total": round(s["total"], 2), "h1": round(s["h1"], 2), "h2": round(s["h2"], 2),
            "exam": round(exam_pnl, 2), "exam_n": len(exam), "train_ok": train_ok, "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    args = ap.parse_args()

    data = backtest.load(args.sim)
    if not data[5]:
        print("Negavau duomenų – apžvalga atidėta.")
        return
    days = (data[5][-1].time - data[5][0].time).days
    cur_name, _ = current_strategy()
    table = []
    print(f"Istorija: {days} d. (mokymasis {days - EXAM_DAYS} d. + egzaminas {EXAM_DAYS} d.)")
    for name, p in config.CANDIDATES.items():
        r = {"name": name, **evaluate(data[p.timeframe], p)}
        table.append(r)
        pf = "∞" if r["pf"] is None else f"{r['pf']:.2f}"
        print(f"{name:<20} sand. {r['n']:>4}  PF {pf:>5}  mokymasis {r['total']:+7.0f} "
              f"({r['h1']:+.0f} / {r['h2']:+.0f})  egzaminas {r['exam']:+6.0f} ({r['exam_n']})  "
              f"{'✅' if r['ok'] else '🟡' if r['train_ok'] else '—'}")

    good = sorted([r for r in table if r["ok"]], key=lambda r: r["total"], reverse=True)
    cur = next((r for r in table if r["name"] == cur_name), None)
    if good and good[0]["name"] != cur_name and (not cur or not cur["ok"] or good[0]["total"] > cur["total"]):
        new = good[0]["name"]
        lesson = (f"Keičiam strategiją: {cur_name} → {new}. Ji buvo pelninga mokymosi metu "
                  f"({good[0]['total']:+.0f} $) ir išlaikė {EXAM_DAYS} d. egzaminą ({good[0]['exam']:+.0f} $).")
    elif cur and cur["ok"]:
        new, lesson = cur_name, f"Liekam prie {cur_name}: ji išlaikė ir mokymąsi, ir egzaminą ({cur['exam']:+.0f} $)."
    else:
        new = cur_name
        lesson = f"Liekam prie {cur_name}, nors egzamino ji neišlaikė – geresnės kandidatės nėra."
    print(lesson)
    save_json(STRATEGY, {"name": new, "chosen_at": datetime.now(timezone.utc).isoformat(),
                         "review": {"at": datetime.now(timezone.utc).isoformat(), "days": days,
                                    "lesson": lesson, "table": table}})


if __name__ == "__main__":
    main()
