"""Kada leidžiama prekiauti MES (CME Globex valandos, Niujorko laiku)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

NY = ZoneInfo("America/New_York")


def _hm(dt: datetime) -> tuple[int, int]:
    return (dt.hour, dt.minute)


def _globex_flat(ny: datetime) -> bool:
    wd = ny.weekday()  # 0 = pirmadienis
    if wd == 5:                                          # šeštadienis
        return True
    if wd == 6 and _hm(ny) < config.REOPEN_AT:           # sekmadienis iki atsidarymo
        return True
    if wd == 4 and _hm(ny) >= config.FLATTEN_AT:         # penktadienio vakaras
        return True
    return config.FLATTEN_AT <= _hm(ny) < config.REOPEN_AT


def must_be_flat(t: datetime, p: config.Params) -> bool:
    """True, kai pozicijos turi būti uždarytos."""
    ny = t.astimezone(NY)
    if _globex_flat(ny):
        return True
    if p.rth_only:
        return ny.weekday() >= 5 or not (config.RTH_START <= _hm(ny) < config.RTH_FLATTEN)
    return False


def can_open(t: datetime, p: config.Params) -> bool:
    """Ar galima atidaryti naują poziciją."""
    if must_be_flat(t, p):
        return False
    if p.rth_only:
        return _hm(t.astimezone(NY)) < config.RTH_LAST_ENTRY
    return True


def trading_day(t: datetime) -> str:
    """Prekybos diena prasideda 18:00 ET (kaip CME), naudojama dienos limitams."""
    ny = t.astimezone(NY)
    if _hm(ny) >= (18, 0):
        ny = ny + timedelta(days=1)
    return ny.strftime("%Y-%m-%d")
