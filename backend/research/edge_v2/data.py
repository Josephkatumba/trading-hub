"""Causal XAUUSD M15 feature frame for Edge Discovery V2.

Every column at row i uses only bars that closed at or before the close of bar i,
except where a name says `_prev` (completed previous period) or `_sofar`.
Trading days roll at 17:00 New York (broker/CFD convention).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .registry import COSTS

BARS = Path(__file__).resolve().parents[2] / "data" / "research" / "edge_v2" / "bars"


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    acc = x[0]
    for k, v in enumerate(x):
        acc = acc + (v - acc) / n if k else v
        out[k] = acc
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2 / (n + 1)
    out = np.empty_like(x, dtype=float)
    acc = x[0]
    for k, v in enumerate(x):
        acc = acc + a * (v - acc) if k else v
        out[k] = acc
    return out


@lru_cache(maxsize=4)
def load(tf: str = "M15") -> pd.DataFrame:
    df = pd.read_csv(BARS / f"XAUUSD_{tf}.csv.gz", parse_dates=["utc"])
    df = df.sort_values("utc").reset_index(drop=True)
    utc = df["utc"].dt.tz_localize("UTC")
    ny = utc.dt.tz_convert("America/New_York")
    ldn = utc.dt.tz_convert("Europe/London")
    df["ny_min"] = ny.dt.hour * 60 + ny.dt.minute
    df["ny_wd"] = ny.dt.weekday
    df["ldn_min"] = ldn.dt.hour * 60 + ldn.dt.minute
    df["ldn_date"] = ldn.dt.date
    df["tday"] = (ny.dt.normalize().dt.tz_localize(None) + pd.to_timedelta((df["ny_min"] >= 17 * 60).astype(int), unit="D"))
    df["spread_px"] = np.maximum(df["spread"].to_numpy(float) * 0.01, COSTS["spread_floor"])

    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    prev_c = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev_c), abs(l - prev_c)))
    df["atr"] = wilder(tr, 14)
    df["atr_prev"] = np.r_[np.nan, df["atr"].to_numpy()[:-1]]

    # trading-day levels
    g = df.groupby("tday")
    day = pd.DataFrame({"hi": g["high"].max(), "lo": g["low"].min(), "op": g["open"].first(), "cl": g["close"].last()})
    day["range"] = day["hi"] - day["lo"]
    day["adr20"] = day["range"].rolling(20, min_periods=10).mean().shift(1)
    day["prev_hi"], day["prev_lo"], day["prev_cl"] = day["hi"].shift(1), day["lo"].shift(1), day["cl"].shift(1)
    day["ret50"] = day["cl"].shift(1) / day["cl"].shift(51) - 1
    df = df.join(day[["op", "adr20", "prev_hi", "prev_lo", "prev_cl", "ret50"]].rename(columns={"op": "day_open"}), on="tday")
    df["day_hi_sofar"] = g["high"].cummax()
    df["day_lo_sofar"] = g["low"].cummin()

    # previous trading week (weeks keyed by the Monday of the trading day)
    wk = df["tday"] - pd.to_timedelta(df["tday"].dt.weekday, unit="D")
    df["week"] = wk
    w = df.groupby("week").agg(whi=("high", "max"), wlo=("low", "min"))
    w["prev_whi"], w["prev_wlo"] = w["whi"].shift(1), w["wlo"].shift(1)
    df = df.join(w[["prev_whi", "prev_wlo"]], on="week")

    # Asian range: London local 00:00-07:00 of the same London date, known from 07:00
    asia = df[df["ldn_min"] < 7 * 60].groupby("ldn_date").agg(asia_hi=("high", "max"), asia_lo=("low", "min"))
    df = df.join(asia, on="ldn_date")
    df.loc[df["ldn_min"] < 7 * 60, ["asia_hi", "asia_lo"]] = np.nan

    # H4 EMA50 slope (last closed H4 bucket)
    h4 = df.set_index("utc")["close"].resample("4h").last().dropna()
    e = pd.Series(ema(h4.to_numpy(), 50), index=h4.index)
    slope = np.sign(e.diff(3))
    h4_close_time = h4.index + pd.Timedelta(hours=4)
    bar_close = df["utc"] + pd.Timedelta(minutes=15)
    k = np.searchsorted(h4_close_time.to_numpy(), bar_close.to_numpy(), side="right") - 1
    df["h4_slope"] = np.where(k >= 0, slope.to_numpy()[np.clip(k, 0, None)], 0)

    # fractal swings (k=2), usable once confirmed two bars later
    sh = (h[2:-2] > np.maximum(h[1:-3], h[:-4])) & (h[2:-2] > np.maximum(h[3:-1], h[4:]))
    sl = (l[2:-2] < np.minimum(l[1:-3], l[:-4])) & (l[2:-2] < np.minimum(l[3:-1], l[4:]))
    sw_hi = np.full(len(df), np.nan)
    sw_lo = np.full(len(df), np.nan)
    sw_hi[np.flatnonzero(sh) + 4] = h[np.flatnonzero(sh) + 2]   # known at j+2
    sw_lo[np.flatnonzero(sl) + 4] = l[np.flatnonzero(sl) + 2]
    df["last_swing_hi"] = pd.Series(sw_hi).ffill().to_numpy()
    df["last_swing_lo"] = pd.Series(sw_lo).ffill().to_numpy()

    df["spread_med"] = df["spread_px"].rolling(1920, min_periods=200).median()
    df["session"] = session_labels(df["ldn_min"].to_numpy(), df["ny_min"].to_numpy())
    gap = df["utc"].diff().shift(-1).dt.total_seconds().to_numpy() / 60
    df["next_gap_min"] = gap
    return df


def session_labels(ldn_min: np.ndarray, ny_min: np.ndarray) -> np.ndarray:
    london = (ldn_min >= 8 * 60) & (ldn_min < 16 * 60 + 30)
    newyork = (ny_min >= 8 * 60) & (ny_min < 17 * 60)
    out = np.where(london & newyork, "overlap", np.where(london, "london", np.where(newyork, "newyork", "asia")))
    return out


def blocked_entry(df: pd.DataFrame) -> np.ndarray:
    """Universal entry filter for the bar AFTER a decision: rollover and scheduled-release bars."""
    nm = df["ny_min"].to_numpy()
    roll = (nm >= 16 * 60 + 45) & (nm < 18 * 60 + 15)
    release = np.isin(nm, [8 * 60 + 30, 10 * 60, 14 * 60])
    weekend = (df["ny_wd"].to_numpy() == 4) & (nm >= 16 * 60)
    return roll | release | weekend
