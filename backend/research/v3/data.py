"""Causal data layer for TradeDen V3.

Bars: IC Markets MT5. H1 times converted from broker time (New York + 7 h) to UTC; D1 bars are broker days
(17:00 New York roll). Real intraday gold exists from Feb 2016; daily gold from 1998; FX H1 from Oct 2010.
USD proxy: the four DXY majors MT5 holds with long history (EUR, JPY, GBP, CHF), DXY weights renormalised.
Macro: ALFRED first-print values as published on each release date (no revisions -> no look-ahead).
Everything a signal reads at decision time t was observable at t; publication lags are explicit.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2] / "data" / "research" / "v3"
BARS, RAW = ROOT / "bars", ROOT / "raw"
USD_WEIGHTS = {"EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119, "USDCHF": 0.036}
RELEASE_NY_MIN = {"CPI": 8 * 60 + 30, "NFP": 8 * 60 + 30, "PCE": 8 * 60 + 30, "FOMC": 14 * 60}


def _ny(utc: pd.Series) -> pd.Series:
    return utc.dt.tz_localize("UTC").dt.tz_convert("America/New_York")


@lru_cache(maxsize=1)
def gold_h1() -> pd.DataFrame:
    df = pd.read_csv(BARS / "XAUUSD_H1.csv.gz", parse_dates=["utc"])
    df = df[df["utc"] >= "2016-02-01"].sort_values("utc").reset_index(drop=True)
    ny = _ny(df["utc"])
    df["ny_date"] = ny.dt.date
    df["ny_hour"] = ny.dt.hour
    df["spread_px"] = df["spread"] * 0.01
    df["usd"] = usd_h1().reindex(df["utc"]).to_numpy()
    df["usd_open"] = usd_h1_open().reindex(df["utc"]).to_numpy()
    return df


@lru_cache(maxsize=1)
def _fx_h1() -> dict:
    out = {}
    for s in USD_WEIGHTS:
        d = pd.read_csv(BARS / f"{s}_H1.csv.gz", parse_dates=["utc"]).drop_duplicates("utc").set_index("utc")
        out[s] = d
    return out


@lru_cache(maxsize=1)
def usd_h1() -> pd.Series:
    fx = _fx_h1()
    idx = sorted(set.intersection(*(set(d.index) for d in fx.values())))
    tot = sum(abs(w) for w in USD_WEIGHTS.values())
    return pd.Series(sum(w * np.log(fx[s].loc[idx, "close"].to_numpy()) for s, w in USD_WEIGHTS.items()) / tot, index=idx)


@lru_cache(maxsize=1)
def usd_h1_open() -> pd.Series:
    fx = _fx_h1()
    idx = sorted(set.intersection(*(set(d.index) for d in fx.values())))
    tot = sum(abs(w) for w in USD_WEIGHTS.values())
    return pd.Series(sum(w * np.log(fx[s].loc[idx, "open"].to_numpy()) for s, w in USD_WEIGHTS.items()) / tot, index=idx)


@lru_cache(maxsize=1)
def gold_d1() -> pd.DataFrame:
    df = pd.read_csv(BARS / "XAUUSD_D1.csv.gz", parse_dates=["broker_date"])
    df = df[df["broker_date"].dt.dayofweek < 5].sort_values("broker_date").reset_index(drop=True)
    df["spread_px"] = df["spread"] * 0.01
    usd = {}
    for s in USD_WEIGHTS:
        d = pd.read_csv(BARS / f"{s}_D1.csv.gz", parse_dates=["broker_date"]).drop_duplicates("broker_date").set_index("broker_date")
        usd[s] = np.log(d["close"])
    u = pd.concat(usd, axis=1).dropna()
    tot = sum(abs(w) for w in USD_WEIGHTS.values())
    df["usd"] = (sum(w * u[s] for s, w in USD_WEIGHTS.items()) / tot).reindex(df["broker_date"]).to_numpy()
    ff = fred("DFF")
    df["dff"] = ff.reindex(df["broker_date"], method="ffill").to_numpy()
    ry = fred("DFII10")
    # real yield is published the next business day: at day t the latest KNOWN value is for t-1
    df["real_yield_known"] = ry.reindex(df["broker_date"] - pd.Timedelta(days=1), method="ffill").to_numpy()
    return df


@lru_cache(maxsize=None)
def fred(sid: str) -> pd.Series:
    d = pd.read_csv(RAW / f"fred_{sid}.csv", parse_dates=["observation_date"])
    s = pd.to_numeric(d[sid], errors="coerce")
    return pd.Series(s.to_numpy(), index=d["observation_date"]).dropna()


def _z_expanding(x: pd.Series, min_n: int = 12) -> pd.Series:
    """Robust z of each value vs PREVIOUS values only (causal): scale = 1.4826 x median absolute deviation,
    so a single COVID-size print cannot inflate the scale for years afterwards; clipped at +/-5."""
    prev = x.shift(1)
    mad = prev.expanding(min_periods=min_n).apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True)
    return (x / (1.4826 * mad)).clip(-5, 5)


@lru_cache(maxsize=1)
def events() -> pd.DataFrame:
    """One row per release with first-print data surprises (positive = hawkish / USD-positive)."""
    rel = json.loads((RAW / "release_dates.json").read_text())
    rows = []

    def first(sid):
        d = pd.read_csv(RAW / f"alfred_first_{sid}.csv", parse_dates=["release_date"]).set_index("release_date")
        return d

    core_cpi = first("CPILFESL")
    s_cpi = (core_cpi["first_value"] / core_cpi["prior_value_then"] - 1) - (core_cpi["prior_value_then"] / core_cpi["prior2_value_then"] - 1)
    core_pce = first("PCEPILFE")
    s_pce = (core_pce["first_value"] / core_pce["prior_value_then"] - 1) - (core_pce["prior_value_then"] / core_pce["prior2_value_then"] - 1)
    pay = first("PAYEMS")
    s_pay = (pay["first_value"] - pay["prior_value_then"]) - ((pay["prior_value_then"] - pay["prior3_value_then"]) / 2)
    ur = first("UNRATE")
    s_ur = -(ur["first_value"] - ur["prior_value_then"])
    z_nfp = pd.concat([_z_expanding(s_pay), _z_expanding(s_ur)], axis=1).mean(axis=1)
    surprise = {"CPI": _z_expanding(s_cpi), "PCE": _z_expanding(s_pce), "NFP": z_nfp}
    for kind in ("CPI", "NFP", "PCE"):
        for d, z in surprise[kind].items():
            rows.append({"kind": kind, "date": pd.Timestamp(d), "data_z": z})
    for d in rel["FOMC"]:
        rows.append({"kind": "FOMC", "date": pd.Timestamp(d), "data_z": np.nan})
    ev = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    ev["ny_min"] = ev["kind"].map(RELEASE_NY_MIN)
    return ev


@lru_cache(maxsize=1)
def cot() -> pd.DataFrame:
    frames = [pd.read_csv(f, low_memory=False) for f in sorted(RAW.glob("cot_gold_*.csv"))]
    d = pd.concat(frames, ignore_index=True).copy()
    d["as_of"] = pd.to_datetime(d["Report_Date_as_YYYY-MM-DD"])
    d = d.drop_duplicates("as_of").sort_values("as_of").reset_index(drop=True)
    oi = d["Open_Interest_All"].astype(float)
    out = pd.DataFrame({
        "as_of": d["as_of"],
        "oi": oi,
        "mm_net": (d["M_Money_Positions_Long_All"] - d["M_Money_Positions_Short_All"]) / oi,
        "pm_net": (d["Prod_Merc_Positions_Long_All"] - d["Prod_Merc_Positions_Short_All"]) / oi,
        "sd_net": (d["Swap_Positions_Long_All"] - d["Swap__Positions_Short_All"]) / oi,
    })
    # usable from the first broker day >= as_of + 6 days (Friday 15:30 ET release + holiday slack)
    out["usable_from"] = out["as_of"] + pd.Timedelta(days=6)
    shutdown = ((out["as_of"] >= "2013-09-24") & (out["as_of"] <= "2013-10-29")) | \
               ((out["as_of"] >= "2018-12-18") & (out["as_of"] <= "2019-03-05"))
    out["publication_disrupted"] = shutdown
    out["cot_index"] = out["mm_net"].rolling(156, min_periods=104).apply(lambda w: (w <= w[-1]).mean(), raw=True)
    return out
