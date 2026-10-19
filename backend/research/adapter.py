"""Integration path (T-033 Phase 6): a research strategy behind the production Strategy contract.

`ReversionShadowStrategy` exposes the leading research candidate (H1 Bollinger mean reversion,
v6.bollinger_reversion with z=2.5, target = 20-bar mean) through strategies.base.Strategy, so it
could run inside the existing scanner -> lifecycle -> outcome -> Telegram pipeline. It is NOT
registered in strategies.REGISTRY and nothing in the engine imports this module.

To integrate (each step needs CEO approval):
  1 register it with mode=SHADOW (records and outcomes only; shadow signals never reach Telegram)
  2 decide a per-strategy minimum reward/risk: production qualification requires >= 1.5R, which
    would reject most mean-reversion trades (median planned R ~1)
  3 let the authoritative outcome resolver track its shadow confirmations for the forward test
  4 only after the forward criteria pass: mode=LIVE

Decision timing: the research entry is the open of the first M15 bar after an H1 close. The adapter
confirms only while the forming M15 bar is that first bar of the forming H1 bar, using H1 bars
closed before it; at any other time it reports WATCHING/NO SETUP.
"""
from __future__ import annotations

import math
from typing import Any

from strategies.base import LIVE, MarketInput, Strategy

Z, BAND_N, SLOPE_N, MAX_SLOPE_ATR = 2.5, 20, 10, 0.3


def _ema(values: list[float], period: int) -> list[float]:
    out, k = [], 2 / (period + 1)
    for v in values:
        out.append(v if not out else out[-1] + k * (v - out[-1]))
    return out


def _atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    trs = []
    for i in range(len(bars) - period, len(bars)):
        b, prev = bars[i], bars[i - 1]["close"]
        trs.append(max(b["high"] - b["low"], abs(b["high"] - prev), abs(b["low"] - prev)))
    return sum(trs) / period


def decide(closed_h1: list[dict[str, Any]], bid: float, ask: float) -> dict[str, Any] | None:
    """The research rule on closed H1 bars (oldest first); entry at the current quote."""
    if len(closed_h1) < 60:
        return None
    closes = [b["close"] for b in closed_h1]
    a = _atr(closed_h1)
    ema50 = _ema(closes, 50)
    if not a or abs(ema50[-1] - ema50[-1 - SLOPE_N]) > MAX_SLOPE_ATR * a:
        return None
    window = closes[-1 - BAND_N:-1]
    mean = sum(window) / BAND_N
    sd = math.sqrt(sum((x - mean) ** 2 for x in window) / BAND_N)
    if not sd:
        return None
    prev, cur = closed_h1[-2], closed_h1[-1]
    for long in (True, False):
        outside = prev["close"] < mean - Z * sd if long else prev["close"] > mean + Z * sd
        back = cur["close"] > mean - Z * sd if long else cur["close"] < mean + Z * sd
        if not (outside and back):
            continue
        extreme = min(prev["low"], cur["low"]) if long else max(prev["high"], cur["high"])
        entry = ask if long else bid
        stop = extreme - a if long else extreme + a
        risk = (entry - stop) if long else (stop - entry)
        reward = (mean - entry) if long else (entry - mean)
        if risk <= 0 or reward <= 0.5 * risk:
            continue
        return {"direction": "LONG" if long else "SHORT", "entry": entry, "stop_loss": stop, "take_profit": mean,
                "mean": mean, "band_sd": sd, "atr": a, "slope_atr": abs(ema50[-1] - ema50[-1 - SLOPE_N]) / a}
    return None


class ReversionShadowStrategy(Strategy):
    strategy_id = "reversion_v6_r1"
    version = "reversion-v6-r1-research"
    timeframe = "H1"
    lifecycle = "CONFIRMED_EVENTS_LIFECYCLE"
    data_requirements = {"M15": 300, "H1": 160}
    intended_mode = LIVE if False else "SHADOW"           # documentation only: never LIVE without approval

    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        h1 = list(market.bars.get("H1") or [])
        rows = list(market.rows or [])
        if len(h1) < 61 or not rows:
            return self._none("Insufficient H1 history for the mean-reversion research strategy.")
        forming_h1, forming_m15 = h1[-1], rows[-1]
        fresh = forming_m15["time"] == forming_h1["time"]       # first M15 bar of the forming H1 bar
        price = forming_m15["close"]
        spread = market.spread or 0.0
        decision = decide(h1[:-1], price, price + spread)
        if not decision:
            return self._none("No stretched-and-reclaimed H1 close in a quiet regime.")
        if not fresh:
            return {**self._none("Signal belongs to the first M15 bar after the H1 close; not re-issued later."),
                    "state": "WATCHING", "direction": decision["direction"]}
        return {"state": "CONFIRMING", "direction": decision["direction"], "strategy_valid": True,
                "entry": decision["entry"], "stop_loss": decision["stop_loss"], "take_profit": decision["take_profit"],
                "invalidation_hint": decision["stop_loss"], "score": None, "score_breakdown": {},
                "reason": (f"H1 close back inside the {Z}-sigma band after closing outside it, in a quiet regime "
                           f"(EMA50 slope {decision['slope_atr']:.2f} ATR); target the 20-bar mean."),
                "setup_family": "MEAN_REVERSION",
                "strategy_evidence": {k: decision[k] for k in ("mean", "band_sd", "atr", "slope_atr")}}

    @staticmethod
    def _none(reason: str) -> dict[str, Any]:
        return {"state": "NO SETUP", "direction": None, "strategy_valid": False, "entry": None, "stop_loss": None,
                "take_profit": None, "invalidation_hint": None, "score": None, "score_breakdown": {}, "reason": reason}
