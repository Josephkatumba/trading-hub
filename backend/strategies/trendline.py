"""The trendline engine as a strategy, by version.

Detection, scoring, confirmation and levels live in scanner.analyze_symbol and are
the same in every version. Versions differ only in how the session context the
scanner receives is computed (London session range, New York alignment):

- trendline-first-v3 (LegacyTrendlineStrategy): London session bars selected by
  reading raw MT5 epochs as UTC. Kept, unregistered, so historical behaviour stays
  reproducible (tests/legacy_session_context.py is the frozen production original).
- trendline-first-v4 (TrendlineStrategy, LIVE): the same session logic with bar
  times converted through the verified broker basis (Phase 8); skipped/repeated
  DST hours are left out, never guessed. Phase 9 A/B: changes only the recorded
  London session fields and the session score (+/-2) with its reason text.

Both share strategy_id "trendline": records keep the version that produced them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

import scanner
from episode_identity import MATCHER_VERSION
from session_time import compute_session_context, corrected_bar_time, legacy_bar_time

from .base import MarketInput, Strategy

LEGACY_VERSION = "trendline-first-v3"


class TrendlineStrategy(Strategy):
    strategy_id = "trendline"
    version = "trendline-first-v4"
    session_time = "broker-basis"    # session bars through the verified MT5 time basis
    timeframe = "M15"
    higher_timeframes = ("H1",)
    lifecycle = MATCHER_VERSION      # episodes follow the existing matcher/lifecycle unchanged
    data_requirements = {"M15": 300, "H1": 160}   # the bars the scan loop has always fetched

    # evaluate() uses rows (M15) and higher_rows (H1) exactly as before; the
    # additional context in market.bars (H4, D1, tick_volume) is not read.

    def session_context(self, rows: Sequence[dict[str, Any]], price: float, now_utc: datetime,
                        basis: str | None) -> dict[str, Any]:
        """Session context for this version (the scan loop passes it back via MarketInput)."""
        return compute_session_context(rows, price, now_utc, corrected_bar_time(basis))

    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        return scanner.analyze_symbol(market.symbol, market.rows, spread=market.spread,
                                      session_context=market.session_context, higher_rows=market.higher_rows,
                                      strategy_version=self.version)


class LegacyTrendlineStrategy(TrendlineStrategy):
    """trendline-first-v3: raw MT5 epochs read as UTC for the London session. Not registered."""
    version = LEGACY_VERSION
    session_time = "raw-epoch-as-utc"

    def session_context(self, rows, price, now_utc, basis=None):
        return compute_session_context(rows, price, now_utc, legacy_bar_time)
