"""Boto smegenys: trys „beždžionės“ – tyrėjas, analitikas ir treideris."""
from __future__ import annotations

from datetime import timedelta

import config
import session
from data_feed import Bar
from paper_broker import PaperBroker


class EMA:
    def __init__(self, n: int):
        self.a, self.v = 2 / (n + 1), None

    def update(self, x: float) -> float:
        self.v = x if self.v is None else self.v + self.a * (x - self.v)
        return self.v


class Engine:
    def __init__(self, broker: PaperBroker, params: config.Params | None = None,
                 news_source=None, log=print):
        self.p = params or config.LIVE
        self.broker = broker
        self.news_source = news_source
        self.log = log
        self.weights = dict(broker.load_extra("weights", self.p.start_weights))
        self.fast, self.slow, self.trend_ema = EMA(self.p.ema_fast), EMA(self.p.ema_slow), EMA(self.p.ema_trend)
        self.prev_diff = 0.0
        self.trend = 0
        self.news_score = 0.0
        self.day = None
        self.day_pnl = 0.0
        self.day_trades = 0
        self.last_bar: Bar | None = None
        self.events: list[str] = []  # kas vyko – rodys beždžionių biuras
        # ORB būsena
        self.orb_day = None
        self.orb_hi = self.orb_lo = None
        self.orb_traded = False
        # Momentum būsena
        self.prev_rth_close = None
        self.day_open = None
        self.mom_ret = None
        # Mean reversion būsena
        from collections import deque
        self.closes = deque(maxlen=self.p.z_len)

    # ---------- analitikas ----------
    def _momentum_signal(self, bar: Bar, t) -> int:
        """Intraday momentum: pirmo pusvalandžio kryptis → paskutinio pusvalandžio sandoris."""
        ny = t.astimezone(session.NY)
        hm = (ny.hour, ny.minute)
        if hm == (9, 35):                       # pirmos 5 min žvakės pradžios kaina
            self.day_open = bar.open
        if hm == (10, 0):
            base = self.prev_rth_close if self.p.mom_from == "prev_close" else self.day_open
            self.mom_ret = (bar.close - base) / base if base else None
            if self.mom_ret is not None:
                self._event(f"📈 Analitikas: pirmas pusvalandis {self.mom_ret:+.2%}")
        sig = 0
        if hm == (15, 25) and self.mom_ret is not None and abs(self.mom_ret) >= self.p.mom_min:
            sig = 1 if self.mom_ret > 0 else -1
        if hm == (16, 0):
            self.prev_rth_close, self.mom_ret = bar.close, None
        return sig

    def _meanrev_signal(self, price: float) -> tuple[int, float]:
        """Jei kaina nutolo > z_entry standartinių nuokrypių nuo vidurkio – lošiam, kad grįš."""
        if len(self.closes) < self.p.z_len:
            return 0, 0.0
        m = sum(self.closes) / len(self.closes)
        sd = (sum((c - m) ** 2 for c in self.closes) / len(self.closes)) ** 0.5
        if sd == 0:
            return 0, 0.0
        z = (price - m) / sd
        if abs(z) >= self.p.z_entry:
            return (-1 if z > 0 else 1), abs(price - m)
        return 0, 0.0
    def _update_emas(self, price: float) -> int:
        """Grąžina +1/-1, jei šioje žvakėje įvyko EMA kryžius, kitaip 0."""
        diff = self.fast.update(price) - self.slow.update(price)
        self.trend_ema.update(price)
        cross = 1 if self.prev_diff <= 0 < diff else -1 if self.prev_diff >= 0 > diff else 0
        self.prev_diff = diff
        if diff:
            self.trend = 1 if diff > 0 else -1
        return cross

    def _trend_allows(self, direction: int, price: float) -> bool:
        if not self.p.trend_filter or self.trend_ema.v is None:
            return True
        return price > self.trend_ema.v if direction > 0 else price < self.trend_ema.v

    def _orb_signal(self, bar: Bar, t) -> int:
        """Opening Range Breakout: +1/-1 kai kaina pirmą kartą užsidaro už ryto ribų."""
        start_ny = bar.time.astimezone(session.NY)
        end_ny = t.astimezone(session.NY)
        if start_ny.date() != self.orb_day:
            self.orb_day, self.orb_hi, self.orb_lo, self.orb_traded = start_ny.date(), None, None, False
        mins = lambda d: d.hour * 60 + d.minute
        open_m = config.RTH_START[0] * 60 + config.RTH_START[1]
        range_end = open_m + self.p.orb_minutes
        if open_m <= mins(start_ny) and mins(end_ny) <= range_end:
            self.orb_hi = bar.high if self.orb_hi is None else max(self.orb_hi, bar.high)
            self.orb_lo = bar.low if self.orb_lo is None else min(self.orb_lo, bar.low)
            if mins(end_ny) == range_end:
                self._event(f"📏 Analitikas: ryto ribos {self.orb_lo:.2f} – {self.orb_hi:.2f}")
            return 0
        if self.orb_hi is None or self.orb_traded or mins(start_ny) < range_end:
            return 0
        if bar.close > self.orb_hi:
            return 1
        if bar.close < self.orb_lo:
            return -1
        return 0

    def _orb_stop(self, direction: int, price: float) -> float:
        dist = price - self.orb_lo if direction > 0 else self.orb_hi - price
        return min(self.p.orb_max_stop, max(self.p.orb_min_stop, dist))

    # ---------- tyrėjas ----------
    def _update_news(self, t):
        self.news_score *= 0.97  # senos naujienos blėsta
        if self.news_source:
            item = self.news_source.latest(t)
            if item:
                self.news_score = item["score"]
                self._event(f"🗞 Tyrėjas: {item['title']} ({item['score']:+.1f})")

    # ---------- treideris ----------
    def on_bar(self, bar: Bar, warmup: bool = False):
        self.last_bar = bar
        cross = self._update_emas(bar.close)
        self.closes.append(bar.close)
        if warmup:
            return

        t = bar.time + timedelta(minutes=self.p.timeframe)  # sprendžiam žvakei užsidarius
        ts = t.isoformat()
        d = session.trading_day(t)
        if d != self.day:  # nauja prekybos diena – nuliname dienos limitus
            self.day, self.day_pnl, self.day_trades = d, 0.0, 0

        self._update_news(t)
        b = self.broker

        # 1) stop / tikslas
        tr = b.check_exits(bar)
        if tr:
            self._after_close(tr)

        # 2) privalomas uždarymas prieš pertrauką / savaitgalį / sesijos pabaigą
        if b.position and session.must_be_flat(t, self.p):
            self._after_close(b.close(bar.close, ts, "sesijos pabaiga"))

        strat = self.p.strategy
        orb = strat == "orb"
        mr_dist = 0.0
        if orb:
            chart_sig = self._orb_signal(bar, t)
            if chart_sig:
                self._event(f"📈 Analitikas: kaina pramušė ryto {'viršutinę' if chart_sig > 0 else 'apatinę'} ribą")
        elif strat == "momentum":
            chart_sig = self._momentum_signal(bar, t)
        elif strat == "meanrev":
            chart_sig, mr_dist = self._meanrev_signal(bar.close)
            if chart_sig and not b.position and session.can_open(t, self.p):
                self._event(f"📈 Analitikas: kaina per toli nuo vidurkio ({mr_dist:.2f} pt) – turėtų grįžti")
        else:
            chart_sig = cross
            if cross:
                self._event(f"📈 Analitikas: EMA{self.p.ema_fast} kirto {'aukštyn' if cross > 0 else 'žemyn'}")

        # 3) sprendimas – tik kai yra naujas signalas (grafiko signalas arba šviežia naujiena)
        fresh_news = abs(self.news_score) > 0.15
        news_sig = self.news_score if fresh_news else 0.0
        # Svertinis vidurkis tik iš aktyvių signalų: vienas signalas irgi gali įvesti,
        # o kai abu aktyvūs – svoriai nusprendžia, kuriuo labiau tikėti.
        wc = self.weights["chart"] if chart_sig else 0.0
        wn = self.weights["news"] if news_sig else 0.0
        score = (wc * chart_sig + wn * news_sig) / (wc + wn) if (wc + wn) else 0.0
        direction = 1 if score > 0 else -1 if score < 0 else 0
        strong = abs(score) >= self.p.entry_threshold

        if b.position and strong and direction == -b.position.dir and strat == "ema":
            self._after_close(b.close(bar.close, ts, "signalas apsisuko"))

        if not b.position and strong and session.can_open(t, self.p) and self._limits_ok():
            if not self._trend_allows(direction, bar.close):
                self._event(f"🚫 Treideris: praleidžiu {'long' if direction > 0 else 'short'} – prieš trendą")
            else:
                name = {"orb": "ORB", "momentum": "momentum", "meanrev": "grįžimas"}.get(strat, "EMA kryžius")
                reason = name if chart_sig else "naujienos"
                if chart_sig and fresh_news and (self.news_score > 0) == (chart_sig > 0):
                    reason = f"{name} + naujienos"
                if orb and self.orb_hi is not None:
                    stop = self._orb_stop(direction, bar.close)
                    target = stop * self.p.orb_target_r
                    self.orb_traded = True
                elif strat == "momentum":
                    stop, target = self.p.stop_pts, 1000.0  # išeinam sesijos pabaigoje
                elif strat == "meanrev" and mr_dist:
                    stop, target = self.p.stop_pts, max(config.TICK * 4, mr_dist)
                else:
                    stop, target = self.p.stop_pts, self.p.target_pts
                pos = b.open(direction, bar.close, ts, reason,
                             {"chart": chart_sig or self.trend, "news": round(self.news_score, 2)},
                             stop, target)
                self.day_trades += 1
                self._event(f"🐒 Treideris: {'PERKA' if direction > 0 else 'PARDUODA'} 1 MES @ {pos.entry:.2f} ({reason})")

        b.save({"weights": self.weights})

    def _limits_ok(self) -> bool:
        if self.day_pnl <= -self.p.max_daily_loss:
            return False
        return self.day_trades < self.p.max_trades_per_day

    # ---------- mokymasis ----------
    def _after_close(self, tr: dict):
        self.day_pnl += tr["pnl"]
        win = tr["pnl"] > 0
        step = self.p.learn_step if win else -self.p.learn_step
        d = 1 if tr["dir"] == "LONG" else -1
        s = tr["signals"]
        clamp = lambda v: round(min(0.9, max(0.1, v)), 3)
        if s.get("chart") == d:
            self.weights["chart"] = clamp(self.weights["chart"] + step)
        if abs(s.get("news", 0)) > 0.15 and (s["news"] > 0) == (d > 0):
            self.weights["news"] = clamp(self.weights["news"] + step)
        self._event(f"{'✅' if win else '❌'} Uždaryta {tr['dir']} {tr['pnl']:+.2f}$ ({tr['reason']})")

    def _event(self, msg: str):
        stamp = self.last_bar.time.astimezone(session.NY).strftime("%m-%d %H:%M ET") if self.last_bar else ""
        line = f"[{stamp}] {msg}"
        self.events = (self.events + [line])[-50:]
        self.log(line)

    # ---------- būsenos išsaugojimas tarp paleidimų (GitHub Actions) ----------
    def export_state(self) -> dict:
        return {"day": self.day, "day_pnl": self.day_pnl, "day_trades": self.day_trades,
                "news_score": self.news_score, "events": self.events[-50:],
                "orb": {"day": self.orb_day.isoformat() if self.orb_day else None,
                        "hi": self.orb_hi, "lo": self.orb_lo, "traded": self.orb_traded},
                "mom": {"prev_close": self.prev_rth_close, "day_open": self.day_open, "ret": self.mom_ret}}

    def import_state(self, s: dict):
        from datetime import date
        o = s.get("orb") or {}
        self.orb_day = date.fromisoformat(o["day"]) if o.get("day") else None
        self.orb_hi, self.orb_lo, self.orb_traded = o.get("hi"), o.get("lo"), o.get("traded", False)
        m = s.get("mom") or {}
        self.prev_rth_close, self.day_open, self.mom_ret = m.get("prev_close"), m.get("day_open"), m.get("ret")
        self.day = s.get("day")
        self.day_pnl = s.get("day_pnl", 0.0)
        self.day_trades = s.get("day_trades", 0)
        self.news_score = s.get("news_score", 0.0)
        self.events = s.get("events", [])

    def status(self) -> dict:
        """Momentinė būsena – ją skaitys beždžionių biuras."""
        b, bar = self.broker, self.last_bar
        price = bar.close if bar else None
        p = b.position
        return {
            "time": bar.time.isoformat() if bar else None,
            "price": price,
            "ema_fast": self.fast.v, "ema_slow": self.slow.v, "ema_trend": self.trend_ema.v,
            "position": None if not p else {"dir": p.dir, "entry": p.entry, "stop": p.stop, "target": p.target},
            "open_pnl": round(b.open_pnl(price), 2) if price else 0,
            "balance": round(b.balance, 2),
            "weights": self.weights,
            "news_score": round(self.news_score, 2),
            "day_pnl": round(self.day_pnl, 2),
            "settings": self.p.label(),
            "events": self.events[-20:],
        }
