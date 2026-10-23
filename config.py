"""Visi boto nustatymai vienoje vietoje."""
from dataclasses import dataclass, field

# --- Instrumentas ---
SYMBOL = "MES=F"          # Yahoo simbolis: Micro E-mini S&P 500 (artimiausias kontraktas)
POINT_VALUE = 5.0         # $ už 1 punktą
TICK = 0.25               # minimalus kainos žingsnis (= $1.25)
COMMISSION_RT = 1.24      # apytiksliai $ už sandorį (įėjimas + išėjimas)
SLIPPAGE_TICKS = 1        # kiek tick'ų prarandame įeinant ir per stop'ą

# --- Sąskaita ---
START_BALANCE = 10_000.0
CONTRACTS = 1

# --- Sesija (Niujorko laiku) ---
# CME Globex: sekm. 18:00 – penkt. 17:00 ET, kasdien pertrauka 17:00–18:00 ET.
FLATTEN_AT = (16, 50)     # visą parą prekiaujant: uždarom prieš pertrauką
REOPEN_AT = (18, 5)
RTH_START = (9, 30)       # JAV akcijų sesija = 16:30 LT
RTH_LAST_ENTRY = (15, 30) # paskutinis įėjimas = 22:30 LT
RTH_FLATTEN = (15, 55)    # uždarom = 22:55 LT

# --- Veikimas ---
POLL_SECONDS = 60
DATA_DIR = "data"         # čia saugomi state.json, trades.csv, status.json


@dataclass
class Params:
    """Strategijos parametrai. backtest.py juos keičia, kad palygintų variantus."""
    strategy: str = "ema"         # "ema" – EMA kryžiai, "orb" – Opening Range Breakout
    timeframe: int = 5            # žvakės ilgis minutėmis (1, 5, 15)
    orb_minutes: int = 15         # ORB: kiek minučių po 9:30 ET (16:30 LT) matuojam ribas
    orb_target_r: float = 2.0     # ORB: tikslas = rizika × R
    orb_max_stop: float = 15.0    # ORB: jei ribos per plačios – stop ne didesnis nei tiek punktų
    orb_min_stop: float = 3.0     # ORB: ir ne mažesnis nei tiek
    mom_from: str = "prev_close"  # momentum: pusvalandžio grąža nuo vakar uždarymo arba "open"
    mom_min: float = 0.0          # momentum: minimali grąža (0.001 = 0.1%)
    z_len: int = 20               # mean reversion: vidurkio langas žvakėmis
    z_entry: float = 2.0          # mean reversion: kiek std nuokrypių nuo vidurkio
    rth_only: bool = True         # prekiauti tik JAV sesijoje (16:30–22:55 LT)
    trend_filter: bool = True     # long tik virš EMA_TREND, short tik po ja
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 50
    stop_pts: float = 6.0         # $30
    target_pts: float = 12.0      # $60
    max_daily_loss: float = 150.0
    max_trades_per_day: int = 10
    entry_threshold: float = 0.3  # |balas| (-1..+1) nuo kurio įeinama
    learn_step: float = 0.03
    start_weights: dict = field(default_factory=lambda: {"news": 0.5, "chart": 0.5})

    def label(self) -> str:
        if self.strategy == "momentum":
            base = "nuo vakar" if self.mom_from == "prev_close" else "nuo 16:30"
            return f"Momentum | 1-as pusvalandis {base} | min {self.mom_min:.1%} | SL {self.stop_pts:g}"
        if self.strategy == "meanrev":
            return f"Grįžimas į vidurkį | {self.timeframe}min | z ≥ {self.z_entry:g} | SL {self.stop_pts:g}"
        if self.strategy == "orb":
            return (f"ORB {self.orb_minutes}min | stop = ribos | TP {self.orb_target_r:g}R | "
                    f"{'su trendu' if self.trend_filter else 'be trendo'}")
        return (f"EMA {self.timeframe}min | {'JAV sesija' if self.rth_only else 'visa para'} | "
                f"{'su trendu' if self.trend_filter else 'be trendo'} | "
                f"SL {self.stop_pts:g} / TP {self.target_pts:g}")


# Šiuo metu naudojami parametrai gyvam botui
LIVE = Params(strategy="meanrev", timeframe=5, trend_filter=False, z_entry=3.0, stop_pts=8.0)

# Kandidatai, iš kurių savaitės apžvalga renkasi (žr. review.py)
CANDIDATES = {
    "Grįžimas z≥3": LIVE,
    "Grįžimas z≥3.5": Params(strategy="meanrev", timeframe=5, trend_filter=False, z_entry=3.5, stop_pts=8.0),
    "EMA 15 min": Params(strategy="ema", timeframe=15, stop_pts=10.0, target_pts=20.0),
    "ORB 15 min": Params(strategy="orb", timeframe=5, orb_minutes=15, orb_target_r=2.0),
    "Momentum 0.2%": Params(strategy="momentum", timeframe=5, trend_filter=False, mom_min=0.002, stop_pts=10.0),
}
