"""Market data for strategies: which timeframes to collect, and what a bar is.

Strategies declare what they need (`Strategy.data_requirements`, e.g.
{"M15": 300, "H1": 160}); the collector fetches the union of the enabled
strategies' requirements plus the shared market context (H4, D1) and hands
every strategy the same `MarketInput.bars`. No strategy logic lives here.

Bars are copied from MT5 as provided: time/open/high/low/close plus
`tick_volume` when the broker supplies it. Nothing is invented or substituted:
a missing field stays absent, and a timeframe the terminal does not support or
has no history for is reported in `unavailable` instead of being filled in.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

# Higher-timeframe context collected for every market, whatever the enabled
# strategies need, so future strategies can use it.
CONTEXT_REQUIREMENTS: dict[str, int] = {"H4": 200, "D1": 200}

# Timeframe names the collector understands (the MetaTrader5 TIMEFRAME_* names).
KNOWN_TIMEFRAMES = ("M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
                    "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1")
OHLC = ("time", "open", "high", "low", "close")


def merge_requirements(requirements: Iterable[Mapping[str, int]]) -> dict[str, int]:
    """Union of timeframe requirements; the largest bar count wins."""
    plan: dict[str, int] = {}
    for requirement in requirements:
        for timeframe, count in requirement.items():
            plan[str(timeframe)] = max(int(count), plan.get(str(timeframe), 0))
    return plan


def plan_for(registry, context: Mapping[str, int] = CONTEXT_REQUIREMENTS) -> dict[str, int]:
    """Timeframes to collect: every enabled strategy's requirements + the shared context."""
    enabled = [registry.get(strategy_id) for strategy_id in registry.enabled()]
    return merge_requirements([*(dict(strategy.data_requirements) for strategy in enabled), context])


def _field(rate: Any, name: str) -> Any:
    names = getattr(getattr(rate, "dtype", None), "names", None)
    if names is not None:                       # numpy record from MetaTrader5
        return rate[name] if name in names else None
    return rate.get(name) if isinstance(rate, Mapping) else None


def bars_from_rates(rates: Iterable[Any]) -> list[dict[str, Any]]:
    """MT5 rates -> bars; tick_volume is kept only when the broker provides it."""
    bars = []
    for rate in rates:
        bar = {key: float(rate[key]) for key in OHLC}
        tick_volume = _field(rate, "tick_volume")
        if tick_volume is not None:
            bar["tick_volume"] = int(tick_volume)
        bars.append(bar)
    return bars


def ohlc_rows(bars: Iterable[Mapping[str, Any]]) -> list[dict[str, float]]:
    return [{key: bar[key] for key in OHLC} for bar in bars]


def fetch_timeframes(mt5: Any, symbol: str, plan: Mapping[str, int],
                     fetched: Mapping[str, list[dict[str, Any]]] | None = None
                     ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Bars per planned timeframe for one symbol, and why any timeframe is unavailable.

    `fetched` holds bars already collected (e.g. the scan's M15/H1 request). They
    are reused when they cover the requested count, so nothing is fetched twice;
    if a larger request fails or returns nothing, the fetched bars are kept as
    they are (never discarded, never padded).
    """
    bars: dict[str, list[dict[str, Any]]] = {}
    unavailable: dict[str, str] = {}
    for timeframe, count in plan.items():
        previous = (fetched or {}).get(timeframe)
        if previous is not None and len(previous) >= count:
            bars[timeframe] = previous
            continue
        code = getattr(mt5, "TIMEFRAME_" + timeframe, None) if timeframe in KNOWN_TIMEFRAMES else None
        reason = None
        if code is None:
            reason = "UNSUPPORTED_TIMEFRAME"
        else:
            try:
                rates = mt5.copy_rates_from_pos(symbol, code, 0, int(count))
                if rates is None or len(rates) == 0:
                    reason = "NO_DATA"
            except Exception:
                reason = "FETCH_FAILED"
        if reason is None:
            bars[timeframe] = bars_from_rates(rates)
        elif previous is not None:
            bars[timeframe] = previous
        else:
            unavailable[timeframe] = reason
    return bars, unavailable


def summary(bars: Mapping[str, list[Mapping[str, Any]]], unavailable: Mapping[str, str], official: bool) -> dict[str, Any]:
    """Public, compact description of the data a market was scanned with."""
    return {"universe": "OFFICIAL" if official else "EXTRA",
            "timeframes": {timeframe: len(rows) for timeframe, rows in bars.items()},
            "unavailable_timeframes": dict(unavailable),
            "tick_volume": {timeframe: bool(rows) and all("tick_volume" in bar for bar in rows)
                            for timeframe, rows in bars.items()}}
