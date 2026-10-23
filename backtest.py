"""Patikrina strategiją su istoriniais duomenimis ir palygina kelis variantus.

    python backtest.py              – palygina variantus su tikrais MES duomenimis (Yahoo)
    python backtest.py --sim        – tas pats su simuliuota rinka
    python backtest.py --live -v    – tik gyvo boto nustatymai, rodo kiekvieną sandorį
"""
import argparse
import sys
from dataclasses import replace

import config
from config import Params
from data_feed import SimFeed, YahooFeed, resample
from engine import Engine
from paper_broker import PaperBroker

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

L = config.LIVE
MOM = replace(L, strategy="momentum", timeframe=5, rth_only=True, trend_filter=False, stop_pts=10)
MR = replace(L, strategy="meanrev", timeframe=5, rth_only=True, trend_filter=False, stop_pts=8)
VARIANTS = [
    L,                                                            # gyvas botas: EMA 15 min
    replace(L, strategy="orb", timeframe=5, orb_minutes=15, orb_target_r=2.0),  # geriausias ORB
    replace(MOM, mom_from="prev_close", mom_min=0.0),
    replace(MOM, mom_from="prev_close", mom_min=0.002),
    replace(MOM, mom_from="open", mom_min=0.0),
    replace(MR, z_entry=2.0),
    replace(MR, z_entry=2.5),
    replace(MR, z_entry=3.0),
]


def run(bars, params: Params, verbose=False):
    broker = PaperBroker(persist=False)
    engine = Engine(broker, params, log=print if verbose else (lambda *_: None))
    warm = params.ema_trend
    for b in bars[:warm]:
        engine.on_bar(b, warmup=True)
    for b in bars[warm:]:
        engine.on_bar(b)
    if broker.position:  # uždarom, kas liko atidaryta
        engine._after_close(broker.close(bars[-1].close, bars[-1].time.isoformat(), "testo pabaiga"))
    return broker, engine


def stats(trades, bars):
    pnl = [t["pnl"] for t in trades]
    wins = [x for x in pnl if x > 0]
    gl = -sum(x for x in pnl if x <= 0)
    eq = peak = dd = 0.0
    for x in pnl:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    mid = bars[len(bars) // 2].time.isoformat()
    h1 = sum(t["pnl"] for t in trades if t["close_time"] < mid)
    return {
        "n": len(pnl), "win": len(wins) / len(pnl) if pnl else 0.0,
        "pf": sum(wins) / gl if gl else float("inf") if wins else 0.0,
        "total": sum(pnl), "dd": dd, "h1": h1, "h2": sum(pnl) - h1,
        "days": (bars[-1].time - bars[0].time).days,
    }


def load(sim: bool):
    """Grąžina {timeframe: žvakės}."""
    if sim:
        f = SimFeed(seed=42)
        one = f.get_bars(40 * 23 * 60, timeframe=1)
        return {1: one[-7 * 23 * 60:], 5: resample(one, 5), 15: resample(one, 15)}
    feed = YahooFeed()
    print("Siunčiu duomenis iš Yahoo (1 min – 7 d., 5 min – 60 d.)...")
    one = feed.get_bars(period="7d", timeframe=1)
    five = feed.get_bars(period="60d", timeframe=5)
    return {1: one, 5: five, 15: resample(five, 15)}


def compare(data):
    print("\n===== VARIANTŲ PALYGINIMAS =====")
    hdr = f"{'#':>2}  {'Nustatymai':<52}{'Dienų':>6}{'Sand.':>7}{'Laim.':>7}{'PF':>6}{'P&L $':>10}{'Nuosm.':>9}{'1-a pusė':>10}{'2-a pusė':>10}"
    print(hdr)
    print("-" * len(hdr))
    for i, p in enumerate(VARIANTS, 1):
        bars = data[p.timeframe]
        if len(bars) < p.ema_trend + 20:
            print(f"{i:>2}  {p.label():<52}  per mažai duomenų")
            continue
        broker, _ = run(bars, p)
        s = stats(broker.trades, bars)
        live = "  ← gyvas botas" if p == config.LIVE else ""
        pf = "∞" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        print(f"{i:>2}  {p.label():<52}{s['days']:>6}{s['n']:>7}{s['win']:>7.0%}{pf:>6}"
              f"{s['total']:>+10.0f}{-s['dd']:>9.0f}{s['h1']:>+10.0f}{s['h2']:>+10.0f}{live}")
    print("\nPF (profit factor) > 1 reiškia pelną. Geras variantas turi būti pliuse ABIEJOSE pusėse –")
    print("jei pelnas tik vienoje, greičiausiai tai atsitiktinumas.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="simuliuota rinka")
    ap.add_argument("--live", action="store_true", help="tik gyvo boto nustatymai")
    ap.add_argument("-v", "--verbose", action="store_true", help="rodyti kiekvieną sandorį")
    args = ap.parse_args()

    data = load(args.sim)
    if not data[5]:
        print("Negavau duomenų. Patikrinkite interneto ryšį arba bandykite --sim.")
        return
    if args.live:
        bars = data[config.LIVE.timeframe]
        broker, engine = run(bars, config.LIVE, args.verbose)
        s = stats(broker.trades, bars)
        print(f"\n{config.LIVE.label()}")
        print(f"Sandorių {s['n']}, laimėta {s['win']:.0%}, P&L {s['total']:+.2f} $, "
              f"nuosmukis -{s['dd']:.2f} $, balansas ${broker.balance:,.2f}")
    else:
        compare(data)


if __name__ == "__main__":
    main()
