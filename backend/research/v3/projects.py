"""Signal generators for Projects A, B and C (rules fixed; only registry grid values vary).

gen(ctx, cfg, fit) -> list[Req].  `fit` = (start, end) of the training window; any threshold that must be
estimated (regime cut-offs, B6 imbalance threshold) is estimated on bars inside `fit` only. All features at
decision bar i use information available at the close of bar i.
"""
from __future__ import annotations

from functools import cached_property

import numpy as np
import pandas as pd

from . import data
from .engine import Req, Series

HOLD = {"1D": ("D1", 1), "H1": ("H1", 1), "H4": ("H1", 4), "D1": ("D1", 1), "5D": ("D1", 5), "1W": ("D1", 5), "4W": ("D1", 20)}


def robust_z(x: pd.Series, min_n: int = 12) -> pd.Series:
    prev = x.shift(1)
    mad = prev.expanding(min_periods=min_n).apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True)
    return (x / (1.4826 * mad)).clip(-5, 5)     # sign relative to zero; scale = robust dispersion of the past


def rolling_robust_z(x: pd.Series, n: int = 250) -> pd.Series:
    prev = x.shift(1)
    mad = prev.rolling(n, min_periods=n // 2).apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True)
    return (x / (1.4826 * mad)).clip(-5, 5)


class Ctx:
    def __init__(self):
        h1 = data.gold_h1()
        d1 = data.gold_d1()
        self.h1df, self.d1df = h1, d1
        h1_dff = data.fred("DFF").reindex(pd.to_datetime(h1["utc"]).dt.normalize(), method="ffill").to_numpy()
        self.s = {"H1": Series("H1", h1, "utc", h1_dff), "D1": Series("D1", d1, "broker_date", d1["dff"].to_numpy())}
        h4 = self._h4(h1)
        h4_dff = data.fred("DFF").reindex(pd.to_datetime(h4["utc"]).dt.normalize(), method="ffill").to_numpy()
        self.s["H4"] = Series("H4", h4, "utc", h4_dff)
        self.ev = data.events()

    @staticmethod
    def _h4(h1: pd.DataFrame) -> pd.DataFrame:
        g = h1.set_index("utc").resample("4h", label="left", closed="left")
        h4 = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                           "close": g["close"].last(), "spread_px": g["spread_px"].max(), "n": g["close"].count()})
        return h4[h4["n"] == 4].drop(columns="n").reset_index()

    # ---------------------------------------------------------------- event tables (causal)
    @cached_property
    def ev_h1(self) -> pd.DataFrame:
        h = self.h1df
        key = {(d, hr): k for k, (d, hr) in enumerate(zip(h["ny_date"], h["ny_hour"]))}
        rows = []
        for e in self.ev.itertuples():
            k = key.get((e.date.date(), e.ny_min // 60))
            if k is None or k + 1 >= len(h):
                continue
            rows.append({"kind": e.kind, "date": e.date, "i": k, "data_z": e.data_z,
                         "usd_ret": h["usd"].iat[k] - h["usd_open"].iat[k],
                         "gold_ret": np.log(h["close"].iat[k] / h["open"].iat[k])})
        df = pd.DataFrame(rows).dropna(subset=["usd_ret"])
        return self._add_z(df)

    @cached_property
    def ev_d1(self) -> pd.DataFrame:
        d = self.d1df
        pos = {dt: k for k, dt in enumerate(d["broker_date"])}
        rows = []
        for e in self.ev.itertuples():
            k = pos.get(e.date)
            if k is None or k < 1:
                continue
            rows.append({"kind": e.kind, "date": e.date, "i": k, "data_z": e.data_z,
                         "usd_ret": d["usd"].iat[k] - d["usd"].iat[k - 1],
                         "gold_ret": np.log(d["close"].iat[k] / d["close"].iat[k - 1])})
        df = pd.DataFrame(rows).dropna(subset=["usd_ret"])
        return self._add_z(df)

    @staticmethod
    def _add_z(df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("date").reset_index(drop=True)
        df["usd_z"] = np.nan
        df["gold_z"] = np.nan
        for kind, g in df.groupby("kind"):
            df.loc[g.index, "usd_z"] = robust_z(g["usd_ret"]).to_numpy()
            df.loc[g.index, "gold_z"] = robust_z(g["gold_ret"]).to_numpy()
        return df

    def events_for(self, horizon: str) -> tuple[pd.DataFrame, str, int]:
        series, hold = HOLD[horizon]
        return (self.ev_h1 if series == "H1" else self.ev_d1), series, hold

    # ---------------------------------------------------------------- COT mapping
    @cached_property
    def cot(self) -> pd.DataFrame:
        c = data.cot().copy()
        dates = self.d1df["broker_date"].to_numpy()
        k = np.searchsorted(dates, c["usable_from"].to_numpy(), side="left")
        c["i"] = k - 1
        return c[(c["i"] >= 0) & (k < len(dates)) & ~c["publication_disrupted"]].reset_index(drop=True)

    # ---------------------------------------------------------------- regime features
    def regime_features(self, tf: str) -> pd.DataFrame:
        key = f"_rf_{tf}"
        if not hasattr(self, key):
            s = self.s[tf]
            c = pd.Series(s.c)
            hi = pd.Series(s.df["high"].to_numpy(float))
            lo = pd.Series(s.df["low"].to_numpy(float))
            er = (c - c.shift(20)).abs() / c.diff().abs().rolling(20).sum()
            lr = np.log(c).diff()
            rv = lr.rolling(20).std()
            vol_pct = rv.rolling(250, min_periods=120).apply(lambda w: (w <= w[-1]).mean(), raw=True)
            sma, sd = c.rolling(20).mean(), c.rolling(20).std()
            f = pd.DataFrame({"er": er, "vol_pct": vol_pct, "mom": np.sign(c - c.shift(20)), "z": (c - sma) / sd,
                              "brk_up": c > hi.shift(1).rolling(20).max(), "brk_dn": c < lo.shift(1).rolling(20).min()})
            setattr(self, key, f)
        return getattr(self, key)


def _in(t, fit) -> np.ndarray:
    return (t >= np.datetime64(fit[0])) & (t < np.datetime64(fit[1]))


# ============================================================ PROJECT A
def a1(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    ev, series, hold = ctx.events_for(cfg["horizon"])
    out = []
    for e in ev.itertuples():
        if np.isfinite(e.usd_z) and abs(e.usd_z) >= cfg["min_abs_z"]:
            out.append(Req(series, e.i, e.i + 1 + hold, -int(np.sign(e.usd_z)), event=series == "H1"))
    return out


def a2(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    ev, series, hold = ctx.events_for(cfg["horizon"])
    d = 1 if cfg["direction"] == "continue" else -1
    return [Req(series, e.i, e.i + 1 + hold, d * int(np.sign(e.gold_z)), event=series == "H1")
            for e in ev.itertuples() if np.isfinite(e.gold_z) and abs(e.gold_z) >= 1.0]


def a3(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    ev, series, hold = ctx.events_for(cfg["horizon"])
    return [Req(series, e.i, e.i + 1 + hold, -int(np.sign(e.data_z)), event=series == "H1")
            for e in ev.itertuples() if e.kind != "FOMC" and np.isfinite(e.data_z) and abs(e.data_z) >= cfg["min_abs_z"]]


def a4(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    ev, series, hold = ctx.events_for(cfg["horizon"])
    kinds = {"CPI", "PCE"} if cfg["events"] == "inflation" else {"CPI", "PCE", "NFP", "FOMC"}
    out = []
    for e in ev.itertuples():
        if e.kind in kinds and np.isfinite(e.usd_z) and abs(e.usd_z) >= 0.5 and np.sign(e.gold_ret) == np.sign(e.usd_ret) != 0:
            out.append(Req(series, e.i, e.i + 1 + hold, -int(np.sign(e.usd_z)), event=series == "H1"))
    return out


def a5(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    """Long from the first bar at or after (statement - window_h hours) to the open of the 13:00 New York bar."""
    ev = ctx.ev_h1
    t = ctx.s["H1"].t
    out = []
    for e in ev[ev["kind"] == "FOMC"].itertuples():
        x = e.i - 1                                     # exit: open of the 13:00 New York bar
        start = t[e.i] - np.timedelta64(cfg["window_h"], "h")
        k = int(np.searchsorted(t, start, side="left"))   # entry bar
        if k < 1 or k >= x or (t[k] - start) > np.timedelta64(2, "h"):
            continue                                    # missing data around the intended entry: skip
        out.append(Req("H1", k - 1, x, 1))
    return out


def a6(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    d = ctx.d1df
    if cfg["driver"] == "usd_proxy":
        chg = d["usd"].diff()
    else:
        chg = d["real_yield_known"].diff()     # already lagged by one business day in data.py
    z = rolling_robust_z(chg)
    hold = HOLD[cfg["hold"]][1]
    return [Req("D1", int(i), int(i) + 1 + hold, -int(np.sign(z.iat[i])))
            for i in np.flatnonzero((z.abs() >= 1.0).to_numpy())]


# ============================================================ PROJECT B
def _cot_reqs(ctx: Ctx, sides: pd.Series, hold_key: str) -> list[Req]:
    c, hold = ctx.cot, HOLD[hold_key][1]
    return [Req("D1", int(c["i"].iat[j]), int(c["i"].iat[j]) + 1 + hold, int(sd))
            for j, sd in sides.items() if np.isfinite(sd) and sd != 0]


def b1(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    hi, lo = (0.9, 0.1) if cfg["band"] == "90_10" else (0.8, 0.2)
    ci = ctx.cot["cot_index"]
    side = pd.Series(np.where(ci >= hi, -1, np.where(ci <= lo, 1, 0)), index=ci.index).where(ci.notna())
    return _cot_reqs(ctx, side, cfg["hold"])


def b2(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    return _cot_reqs(ctx, np.sign(ctx.cot["mm_net"].diff(cfg["change_w"])), cfg["hold"])


def b3(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    return _cot_reqs(ctx, np.sign(ctx.cot["pm_net"].diff(cfg["change_w"])), cfg["hold"])


def b4(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    c = ctx.cot
    close = ctx.s["D1"].c
    px = pd.Series([close[i] / close[i - 20] - 1 if i >= 20 else np.nan for i in c["i"]])
    oi_up = c["oi"].diff(4) > 0
    side = np.sign(px).where(oi_up, 0)
    return _cot_reqs(ctx, side, cfg["hold"])


def b6(ctx: Ctx, cfg: dict, fit) -> list[Req]:
    h = ctx.h1df
    sgn = np.sign(h["close"] - h["open"])
    tv = h["tick_volume"].astype(float)
    imb = (tv * sgn).rolling(24).sum() / tv.rolling(24).sum()
    thr = np.nanquantile(np.abs(imb.to_numpy()[_in(ctx.s["H1"].t, fit)]), 0.8)
    d = 1 if cfg["direction"] == "follow" else -1
    hold = HOLD[cfg["hold"]][1] if cfg["hold"] == "H4" else 24
    return [Req("H1", int(i), int(i) + 1 + hold, d * int(np.sign(imb.iat[i])))
            for i in np.flatnonzero((imb.abs() >= thr).to_numpy())]


# ============================================================ PROJECT C
STRATEGY_HOLD = {"MOM": 5, "MR": 5, "BRK": 10}


def strategy_sides(f: pd.DataFrame, strat: str) -> np.ndarray:
    if strat == "MOM":
        return f["mom"].fillna(0).to_numpy()
    if strat == "MR":
        return np.where(f["z"] <= -1.5, 1, np.where(f["z"] >= 1.5, -1, 0))
    return np.where(f["brk_up"], 1, np.where(f["brk_dn"], -1, 0))


def regime_mask(ctx: Ctx, tf: str, regime: str, fit) -> np.ndarray:
    f = ctx.regime_features(tf)
    if regime in ("TREND", "RANGE"):
        er_fit = f["er"].to_numpy()[_in(ctx.s[tf].t, fit)]
        q33, q67 = np.nanquantile(er_fit, [1 / 3, 2 / 3])
        return (f["er"] >= q67).to_numpy() if regime == "TREND" else (f["er"] <= q33).to_numpy()
    if regime == "LOWVOL":
        return (f["vol_pct"] <= 1 / 3).to_numpy()
    return (f["vol_pct"] >= 2 / 3).to_numpy()


def c1(ctx: Ctx, cfg: dict, fit, conditional: bool = True) -> list[Req]:
    strat, regime = cfg["pair"].split("|")
    tf = cfg["tf"]
    f = ctx.regime_features(tf)
    side = strategy_sides(f, strat)
    ok = side != 0
    if conditional:
        ok &= regime_mask(ctx, tf, regime, fit)
    hold = STRATEGY_HOLD[strat]
    return [Req(tf, int(i), int(i) + 1 + hold, int(side[i])) for i in np.flatnonzero(ok)]


GENERATORS = {
    "A1_usd_reaction_underreaction": a1, "A2_gold_reaction_persistence": a2, "A3_data_surprise_drift": a3,
    "A4_gold_usd_divergence": a4, "A5_pre_fomc_drift": a5, "A6_rates_dollar_leadlag": a6,
    "B1_cot_extremes_contrarian": b1, "B2_cot_mm_flow_momentum": b2, "B3_cot_hedger_flow": b3,
    "B4_oi_price_confirmation": b4, "B6_tick_volume_imbalance_proxy": b6, "C1_regime_conditional": c1,
}


def layer(name: str, cfg: dict) -> str:
    if name.startswith("B6"):
        return "intraday"
    if name.startswith("C1"):
        return "regime_d1" if cfg["tf"] == "D1" else "intraday"
    hz = cfg.get("horizon") or cfg.get("hold")
    if name.startswith("A5") or (hz and HOLD.get(hz, ("D1",))[0] == "H1"):
        return "intraday"
    return "daily"
