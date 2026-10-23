"""Kainų šaltiniai: tikri MES duomenys iš Yahoo arba simuliacija testams."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import config


@dataclass
class Bar:
    time: datetime   # žvakės pradžia, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Sujungia žvakes į ilgesnes (pvz. 5 min → 15 min), lygiuojant pagal laikrodį."""
    if minutes <= 1 or not bars:
        return list(bars)
    out: list[Bar] = []
    for b in bars:
        start = b.time.replace(second=0, microsecond=0)
        start -= timedelta(minutes=start.minute % minutes)
        if out and out[-1].time == start:
            o = out[-1]
            o.high, o.low, o.close = max(o.high, b.high), min(o.low, b.low), b.close
            o.volume += b.volume
        else:
            out.append(Bar(start, b.open, b.high, b.low, b.close, b.volume))
    return out


class YahooFeed:
    """Nemokami MES duomenys. Yahoo futures kotiruotės vėluoja ~10 min.
    Ribos: 1 min – 7 dienos istorijos, 5/15 min – 60 dienų."""

    def __init__(self, symbol: str = config.SYMBOL):
        import yfinance as yf  # importuojam tik kai reikia
        self.ticker = yf.Ticker(symbol)

    def get_bars(self, period: str = "5d", timeframe: int = 5) -> list[Bar]:
        df = self.ticker.history(period=period, interval=f"{timeframe}m", prepost=True)
        if df.empty:
            return []
        bars = [
            Bar(ts.to_pydatetime().astimezone(timezone.utc),
                float(r.Open), float(r.High), float(r.Low), float(r.Close), float(r.Volume))
            for ts, r in df.iterrows()
        ]
        # paskutinė žvakė dar formuojasi – jos neimam
        now = datetime.now(timezone.utc)
        if bars and bars[-1].time > now - timedelta(minutes=timeframe):
            bars = bars[:-1]
        return bars


class SimFeed:
    """Atsitiktinė rinka – kad būtų galima testuoti be interneto ar savaitgalį."""

    def __init__(self, start_price: float = 6850.0, seed: int | None = None,
                 start: datetime | None = None):
        self.rng = random.Random(seed)
        self.price = start_price
        self.drift = 0.0
        self.t = start or datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc)  # pirmadienis 9:30 ET

    def _r4(self, p: float) -> float:
        return round(p / config.TICK) * config.TICK

    def _next_1m(self) -> Bar:
        if self.rng.random() < 0.02:
            self.drift += self.rng.choice([-1, 1]) * self.rng.uniform(0.3, 0.8)
        self.drift *= 0.95
        o = self.price
        path = [o]
        for _ in range(4):
            path.append(path[-1] + self.drift / 4 + self.rng.gauss(0, 0.6))
        c = self._r4(path[-1])
        bar = Bar(self.t, o, self._r4(max(path)), self._r4(min(path)), c,
                  abs(self.rng.gauss(800, 300)))
        self.price = c
        self.t += timedelta(minutes=1)
        return bar

    def get_bars(self, n: int = 1, timeframe: int = 5) -> list[Bar]:
        """n žvakių po `timeframe` minučių."""
        return resample([self._next_1m() for _ in range(n * timeframe)], timeframe)
