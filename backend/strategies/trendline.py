"""The existing trendline engine as a strategy.

A pure adapter: evaluate() returns exactly what scanner.analyze_symbol returns
for the same input. Detection, scoring, confirmation and levels stay in
scanner.py, untouched. setup_family (BREAK / REVERSAL / None for directional
context) already distinguishes the trendline setups inside the payload.
"""
from __future__ import annotations

from typing import Any

import scanner
from episode_identity import MATCHER_VERSION

from .base import MarketInput, Strategy


class TrendlineStrategy(Strategy):
    strategy_id = "trendline"
    version = "trendline-first-v3"   # the strategy_version analyze_symbol reports
    timeframe = "M15"
    higher_timeframes = ("H1",)
    lifecycle = MATCHER_VERSION      # episodes follow the existing matcher/lifecycle unchanged

    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        return scanner.analyze_symbol(market.symbol, market.rows, spread=market.spread,
                                      session_context=market.session_context, higher_rows=market.higher_rows)
