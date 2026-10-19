"""Bar-by-bar replay of production strategies over cached history, without look-ahead.

At M15 bar i the replay is "the scan that ran the moment bar i opened":

  M15 rows   the 300 closed bars before i, plus bar i as the forming bar, holding only
             what was known at its open (open = high = low = close = its open)
  H1/H4/D1   their closed bars (open time + duration <= bar i's open), plus their forming
             bar built from the M15 bars already closed inside it and bar i's open
  quote      bid = bar i's open (MT5 bars are bid), ask = bid + the spread recorded on bar i

so no value from after bar i's open can reach a strategy. The production post-processing
(trade_planning.apply_plan, then qualification.apply at that quote) is applied exactly as
main._market_snapshot does. Production strategy code is called, never copied.

A strategy confirming on consecutive bars is one setup, as in production (one
confirmation per episode): a signal is emitted on the bar its confirmation starts (or its
direction changes), and not while a previous signal of the same strategy and symbol is
still open in the simulation (lab.py enforces the latter).
"""
from __future__ import annotations

import bisect
import math
from typing import Any, Iterator

import qualification
from research import history
from strategies.base import MarketInput
from trade_planning import apply_plan

M15_COUNT, COUNTS = 300, {"H1": 160, "H4": 200, "D1": 200}
KEEP = ("time", "open", "high", "low", "close", "tick_volume")


def _strip(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: bar[key] for key in KEEP} for bar in bars]


class SymbolHistory:
    def __init__(self, symbol: str, meta: dict[str, Any], bars: dict[str, list[dict[str, Any]]]) -> None:
        self.symbol, self.meta = symbol, meta
        self.full = bars
        self.rows = {tf: _strip(b) for tf, b in bars.items() if tf != "M1"}
        self.raw = {tf: [b["time"] for b in rows] for tf, rows in self.rows.items()}
        self.m1_utc = [b["utc"] for b in bars.get("M1", [])]

    @classmethod
    def load(cls, symbol: str) -> "SymbolHistory":
        meta = history.manifest().get("symbols", {}).get(symbol, {}).get("meta") or {}
        return cls(symbol, meta, {tf: history.load(symbol, tf) for tf in ("M15", "H1", "H4", "D1", "M1")})

    def first_index(self) -> int:
        return M15_COUNT

    def _higher(self, timeframe: str, now_raw: float, i: int) -> list[dict[str, Any]] | None:
        rows, times = self.rows.get(timeframe) or [], self.raw.get(timeframe) or []
        seconds = history.TIMEFRAME_SECONDS[timeframe]
        j = bisect.bisect_right(times, now_raw) - 1          # last bar opened at or before now
        if j < 0:
            return None
        if times[j] + seconds <= now_raw:                    # bar j already closed: a new bar would be forming
            closed_end, forming_open = j + 1, now_raw - (now_raw - times[j]) % seconds
        else:
            closed_end, forming_open = j, times[j]
        count = COUNTS[timeframe]
        if closed_end < count:
            return None
        m15 = self.rows["M15"]
        lo = bisect.bisect_left(self.raw["M15"], forming_open)
        inside = m15[lo:i]                                   # closed M15 bars inside the forming bar
        price = m15[i]["open"]
        forming = {"time": forming_open, "open": inside[0]["open"] if inside else price,
                   "high": max([b["high"] for b in inside] + [price]), "low": min([b["low"] for b in inside] + [price]),
                   "close": price, "tick_volume": sum(b["tick_volume"] for b in inside)}
        return rows[closed_end - count:closed_end] + [forming]

    def market_input(self, i: int) -> tuple[MarketInput, dict[str, Any]] | None:
        m15 = self.rows["M15"]
        if i < M15_COUNT or i >= len(m15):
            return None
        bar = m15[i]
        forming = {"time": bar["time"], "open": bar["open"], "high": bar["open"], "low": bar["open"],
                   "close": bar["open"], "tick_volume": 0}
        rows = m15[i - M15_COUNT:i] + [forming]
        frames = {"M15": rows}
        for timeframe in COUNTS:
            higher = self._higher(timeframe, bar["time"], i)
            if higher is None:
                return None
            frames[timeframe] = higher
        spread = self.full["M15"][i]["spread"]
        bid = bar["open"]
        quote = {"symbol": self.symbol, "bid": bid, "ask": bid + spread, "price": bid + spread / 2, "spread": spread,
                 "tick_age_seconds": 0.0, "digits": self.meta.get("digits"), "point": self.meta.get("point"),
                 "tick_size": self.meta.get("tick_size")}
        ohlc = lambda bars: [{k: b[k] for k in ("time", "open", "high", "low", "close")} for b in bars]
        market = MarketInput(self.symbol, ohlc(rows), spread, None, ohlc(frames["H1"]), frames, {})
        return market, quote


def production_setup(strategy: Any, market: MarketInput, quote: dict[str, Any]) -> dict[str, Any] | None:
    """The strategy's payload after production planning + qualification, or None on error."""
    try:
        payload = strategy.evaluate(market)
    except Exception:
        return None
    if not payload:
        return None
    setup = {**quote, **payload, "strategy_id": strategy.strategy_id, "strategy_version": strategy.version}
    apply_plan(setup, market.bars)
    qualification.apply(setup)
    return setup


SCALARS = (int, float, str, bool, type(None))


def compact(setup: dict[str, Any]) -> dict[str, Any]:
    """Scalar evidence kept with a signal (for experiment filters), plus score breakdown."""
    out = {k: v for k, v in setup.items() if isinstance(v, SCALARS) and not (isinstance(v, float) and not math.isfinite(v))}
    out["score_breakdown"] = {k: v for k, v in (setup.get("score_breakdown") or {}).items() if isinstance(v, (int, float))}
    q = setup.get("qualification") or {}
    out["executable_rr"] = q.get("executable_rr")
    return out


def signals(history_: SymbolHistory, strategy: Any, start_utc: float, end_utc: float) -> Iterator[dict[str, Any]]:
    """Confirmation onsets of `strategy` between start_utc and end_utc (UTC bar-open times)."""
    full = history_.full["M15"]
    previous: str | None = None
    for i in range(history_.first_index(), len(full)):
        utc = full[i]["utc"]
        if utc < start_utc:
            continue
        if utc >= end_utc:
            break
        built = history_.market_input(i)
        if built is None:
            previous = None
            continue
        setup = production_setup(strategy, *built)
        confirmed = bool(setup and setup.get("strategy_valid") is True and setup.get("direction") in ("LONG", "SHORT"))
        key = setup.get("direction") if confirmed else None
        if confirmed and key != previous:
            yield {"index": i, "utc": utc, "symbol": history_.symbol, "strategy_id": strategy.strategy_id,
                   "strategy_version": strategy.version, "direction": setup["direction"],
                   "entry": setup.get("entry"), "stop_loss": setup.get("stop_loss"), "take_profit": setup.get("take_profit"),
                   "spread": built[1]["spread"], "evidence": compact(setup)}
        previous = key
