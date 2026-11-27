"""Instrument specs, cost model and M1 data loading.

Costs are deliberately conservative. Spreads come from the bar data but are
floored, because MT5 bar spreads record the *minimum* spread of the minute.
Commission follows IC Markets' cTrader Raw schedule ($3 per $100k notional
per side). The cBot logs the commission cTrader actually charges, so live
results never depend on these assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Instrument:
    symbol: str
    point: float            # price increment of the MT5 `spread` column
    spread_floor: float     # minimum assumed spread, in price
    slippage: float         # adverse price per market fill (entry, stop, time exit)
    commission_rate: float  # per side, fraction of notional
    volume_step: float      # units (oz, BTC, currency units)
    volume_min: float
    crypto: bool = False


INSTRUMENTS = {
    "XAUUSD": Instrument("XAUUSD", 0.01, 0.08, 0.03, 3e-5, 1.0, 1.0),
    "BTCUSD": Instrument("BTCUSD", 0.01, 6.0, 3.0, 3e-5, 0.01, 0.01, crypto=True),
    "EURUSD": Instrument("EURUSD", 1e-5, 0.00002, 0.00002, 3e-5, 1000.0, 1000.0),
    "GBPUSD": Instrument("GBPUSD", 1e-5, 0.00004, 0.00002, 3e-5, 1000.0, 1000.0),
}


def broker_to_utc(times: pd.Series) -> pd.Series:
    """IC Markets MT5 server time is New York time + 7h (GMT+2 / GMT+3)."""
    ny_naive = times - pd.Timedelta(hours=7)
    return (ny_naive.dt.tz_localize(NY, ambiguous="NaT", nonexistent="shift_forward")
            .dt.tz_convert("UTC").dt.tz_localize(None))


def load_m1(symbol: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{symbol}_M1.csv.gz")
    df["time"] = broker_to_utc(pd.to_datetime(df["time"]))
    df = df.dropna(subset=["time"]).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    inst = INSTRUMENTS[symbol]
    df["spread_px"] = np.maximum(df["spread"].astype(float) * inst.point, inst.spread_floor)
    return df[["time", "open", "high", "low", "close", "spread_px"]]


def resample(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    g = m1.set_index("time").resample(f"{minutes}min", label="left", closed="left")
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "spread_px": g["spread_px"].mean(),
    }).dropna().reset_index()
    return out


def export_from_mt5(symbols=tuple(INSTRUMENTS), bars: int = 99_999) -> None:
    """Refresh data/<symbol>_M1.csv.gz from a logged-in MetaTrader 5 terminal."""
    import MetaTrader5 as mt5  # optional dependency

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    DATA_DIR.mkdir(exist_ok=True)
    for s in symbols:
        mt5.symbol_select(s, True)
        rates = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M1, 0, bars)
        if rates is None:
            raise RuntimeError(f"{s}: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.to_csv(DATA_DIR / f"{s}_M1.csv.gz", index=False)
