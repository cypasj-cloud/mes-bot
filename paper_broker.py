"""Popierinis brokeris: veda pozicijas, stop'us, P&L ir sandorių žurnalą."""
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass, field

import config
from data_feed import Bar


@dataclass
class Position:
    dir: int            # +1 long, -1 short
    entry: float
    stop: float
    target: float
    time: str
    reason: str
    signals: dict = field(default_factory=dict)  # kokie signalai buvo įeinant (mokymuisi)


class PaperBroker:
    def __init__(self, data_dir: str = config.DATA_DIR, persist: bool = True):
        self.data_dir = data_dir
        self.persist = persist
        self.balance = config.START_BALANCE
        self.position: Position | None = None
        self.trades: list[dict] = []
        if persist:
            os.makedirs(data_dir, exist_ok=True)
            self._load()

    # ---------- saugojimas ----------
    @property
    def _state_path(self):
        return os.path.join(self.data_dir, "state.json")

    def _load(self):
        if not os.path.exists(self._state_path):
            return
        with open(self._state_path, encoding="utf-8") as f:
            s = json.load(f)
        self.balance = s["balance"]
        self.position = Position(**s["position"]) if s.get("position") else None

    def save(self, extra: dict | None = None):
        if not self.persist:
            return
        s = {"balance": self.balance,
             "position": asdict(self.position) if self.position else None}
        if extra:
            s.update(extra)
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)

    def load_extra(self, key: str, default):
        if self.persist and os.path.exists(self._state_path):
            with open(self._state_path, encoding="utf-8") as f:
                return json.load(f).get(key, default)
        return default

    # ---------- prekyba ----------
    def _slip(self, dir: int) -> float:
        return dir * config.SLIPPAGE_TICKS * config.TICK

    def open(self, dir: int, price: float, time: str, reason: str, signals: dict,
             stop_pts: float, target_pts: float):
        fill = price + self._slip(dir)  # perkam brangiau / parduodam pigiau
        self.position = Position(dir, fill,
                                 fill - dir * stop_pts,
                                 fill + dir * target_pts,
                                 time, reason, signals)
        return self.position

    def close(self, price: float, time: str, why: str, slip: bool = True) -> dict:
        p = self.position
        fill = price - (self._slip(p.dir) if slip else 0.0)
        pnl = (fill - p.entry) * p.dir * config.POINT_VALUE * config.CONTRACTS - config.COMMISSION_RT
        self.balance += pnl
        trade = {"open_time": p.time, "close_time": time,
                 "dir": "LONG" if p.dir > 0 else "SHORT",
                 "entry": p.entry, "exit": round(fill, 2), "pnl": round(pnl, 2),
                 "reason": f"{p.reason} → {why}", "signals": p.signals}
        self.trades.append(trade)
        self.position = None
        self._append_csv(trade)
        return trade

    def check_exits(self, bar: Bar) -> dict | None:
        """Ar per šią žvakę suveikė stop arba tikslas. Jei abu – laikom, kad stop (atsargiau)."""
        p = self.position
        if not p:
            return None
        t = bar.time.isoformat()
        hit_stop = bar.low <= p.stop if p.dir > 0 else bar.high >= p.stop
        hit_tgt = bar.high >= p.target if p.dir > 0 else bar.low <= p.target
        if hit_stop:
            # jei žvakė atsidarė už stop'o (gap) – užpildom atidarymo kaina
            px = min(bar.open, p.stop) if p.dir > 0 else max(bar.open, p.stop)
            return self.close(px, t, "stop-loss")
        if hit_tgt:
            return self.close(p.target, t, "tikslas", slip=False)
        return None

    def open_pnl(self, price: float) -> float:
        p = self.position
        return (price - p.entry) * p.dir * config.POINT_VALUE * config.CONTRACTS if p else 0.0

    def _append_csv(self, t: dict):
        if not self.persist:
            return
        path = os.path.join(self.data_dir, "trades.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["open_time", "close_time", "dir", "entry", "exit", "pnl", "reason"])
            w.writerow([t["open_time"], t["close_time"], t["dir"], t["entry"], t["exit"],
                        t["pnl"], t["reason"]])
