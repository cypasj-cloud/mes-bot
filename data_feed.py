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


class DatabentoHistory:
    """Ilga tikra MES 1 min istorija iš Databento (CME Globex).

    Duomenys kešuojami data/history_mes_1m.csv.gz – kiekvieną kartą parsisiunčiamos
    tik naujos dienos, todėl tas pats nemokama/mokama dalis nesiunčiama dukart.
    Kontraktų keitimas (roll) kas ketvirtį suglodinamas: senesnės kainos perstumiamos
    per skirtumą tarp senojo ir naujojo kontrakto (back-adjust), kad nebūtų netikro šuolio.
    """
    DATASET = "GLBX.MDP3"
    SYMBOL = "MES.v.0"          # artimiausias kontraktas pagal apyvartą
    CACHE = ".cache/history_mes_1m.csv.gz"  # ne repozitorijoje – GitHub Actions cache

    def __init__(self, key: str | None = None, cache: str = CACHE):
        import os
        self.key = key or os.environ.get("DATABENTO_API_KEY")
        self.cache = cache

    def available(self) -> bool:
        return bool(self.key)

    # ---------- kešas ----------
    def _read_cache(self):
        import os
        import pandas as pd
        if not os.path.exists(self.cache):
            return None
        df = pd.read_csv(self.cache, parse_dates=["ts"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df

    def _write_cache(self, df):
        import os
        os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        df.to_csv(self.cache, index=False, compression="gzip", float_format="%.2f")

    # ---------- siuntimas ----------
    def _download(self, start, end):
        import databento as db
        import pandas as pd
        client = db.Historical(self.key)
        try:  # neprašyti duomenų, kurių Databento dar neturi
            avail = pd.Timestamp(client.metadata.get_dataset_range(dataset=self.DATASET)["end"])
            avail = avail.tz_localize("UTC") if avail.tzinfo is None else avail
            end = min(pd.Timestamp(end), avail).to_pydatetime()
        except Exception:
            pass
        if end <= start:
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "inst"])
        kw = dict(dataset=self.DATASET, symbols=[self.SYMBOL], stype_in="continuous",
                  schema="ohlcv-1m", start=start.isoformat(), end=end.isoformat())
        try:
            cost = client.metadata.get_cost(**kw)
            print(f"Databento: siunčiu {start:%Y-%m-%d} – {end:%Y-%m-%d}, kaina ~${cost:.4f}")
        except Exception as e:  # kainos užklausa nebūtina
            print(f"Databento: kainos nepavyko sužinoti ({e})")
        raw = client.timeseries.get_range(**kw).to_df()
        if raw.empty:
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "inst"])
        raw = raw.reset_index()
        tcol = "ts_event" if "ts_event" in raw.columns else raw.columns[0]
        return pd.DataFrame({
            "ts": pd.to_datetime(raw[tcol], utc=True),
            "open": raw["open"].astype(float), "high": raw["high"].astype(float),
            "low": raw["low"].astype(float), "close": raw["close"].astype(float),
            "volume": raw["volume"].astype(float), "inst": raw["instrument_id"].astype(int),
        })

    def update(self, days: int = 160):
        """Atnaujina kešą iki vakar ir grąžina visą (≤ days dienų) lentelę."""
        import pandas as pd
        end = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(second=0, microsecond=0)
        want_start = (end - timedelta(days=days)).replace(hour=0, minute=0)
        df = self._read_cache()
        parts = [] if df is None else [df]
        if df is None or df.empty or df["ts"].min() > want_start + timedelta(days=3):
            parts.append(self._download(want_start, end if df is None or df.empty else df["ts"].min().to_pydatetime()))
        if df is not None and not df.empty:
            last = df["ts"].max().to_pydatetime() + timedelta(minutes=1)
            if end - last > timedelta(minutes=30):
                parts.append(self._download(last, end))
        df = pd.concat([p for p in parts if p is not None and not p.empty], ignore_index=True)
        df = df.drop_duplicates("ts").sort_values("ts")
        df = df[df["ts"] >= pd.Timestamp(want_start)].reset_index(drop=True)
        self._write_cache(df)
        return df

    @staticmethod
    def back_adjust(df):
        """Suglodina kontraktų keitimą: ankstesnės kainos perstumiamos per roll tarpą."""
        df = df.copy()
        change = df.index[df["inst"].ne(df["inst"].shift()) & df.index.to_series().gt(0)]
        for i in reversed(list(change)):
            gap = df.at[i, "open"] - df.at[i - 1, "close"]
            df.loc[: i - 1, ["open", "high", "low", "close"]] += gap
        return df

    def get_bars(self, days: int = 160, timeframe: int = 5) -> list[Bar]:
        df = self.back_adjust(self.update(days))
        one = [Bar(t.to_pydatetime(), o, h, l, c, v) for t, o, h, l, c, v in
               zip(df["ts"], df["open"], df["high"], df["low"], df["close"], df["volume"])]
        return resample(one, timeframe)


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
