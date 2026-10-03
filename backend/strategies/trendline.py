"""The trendline engine as a strategy, by version.

Detection, scoring, confirmation and levels live in scanner.analyze_symbol and are
the same in every version. Versions differ only in how the session context the
scanner receives is computed (London session range, New York alignment):

- trendline-first-v3 (LegacyTrendlineStrategy): London session bars selected by
  reading raw MT5 epochs as UTC. Kept, unregistered, so historical behaviour stays
  reproducible (tests/legacy_session_context.py is the frozen production original).
- trendline-first-v4 (TrendlineStrategy, strategy_id "trendline"): the same session
  logic with bar times converted through the verified broker basis (Phase 8);
  skipped/repeated DST hours are left out, never guessed. RETIRED from live use:
  kept, unregistered, so its historical records stay reproducible.

- trendline-first-v5 (TrendlineV5Strategy, strategy_id "trendline_v5", LIVE): the same
  detection, scoring and confirmation rules evaluated on CLOSED bars only (the last
  M15 and H1 rows the scan fetches are still forming), with the session context taken
  from closed M15 bars at the last closed bar's close, and the H1 structural target
  model (scanner._trade_levels, structural_levels). The stop and the 1.5R gate are
  unchanged. Being a pure function of closed bars, it cannot repaint within a bar.
  Lifecycle: CONFIRMED_EVENTS_LIFECYCLE (as Trend / Momentum), so a confirmed setup is
  closed only by its confirmed stop or target, never by a later direction change.

v3 and v4 share strategy_id "trendline" (records keep the version that produced them).
v5 has its own strategy_id "trendline_v5": its episodes, suppression, lifecycle policy,
confirmations, outcomes and performance are scoped by strategy_id, so they never mix
with the old trendline history. The Garden labels both TRENDLINE; the version is on
every record.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import scanner
from episode_identity import CONFIRMED_EVENTS_LIFECYCLE, MATCHER_VERSION
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


V5_VERSION = "trendline-first-v5"
M15 = timedelta(minutes=15)


def closed_bars(rows: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The scan fetches bars from position 0, so the last row is the still-forming bar."""
    return list(rows or [])[:-1]


V5_STRATEGY_ID = "trendline_v5"


class TrendlineV5Strategy(TrendlineStrategy):
    """trendline-first-v5: closed bars only + H1 structural targets. The LIVE trendline."""
    strategy_id = V5_STRATEGY_ID
    version = V5_VERSION
    # Confirmed setups are historical events (as Trend / Momentum): once CONFIRMED/ACTIVE,
    # a later observation in the other direction or family is a competing episode and
    # never closes it; it resolves only at its confirmed stop or target
    # (episode_identity.CONFIRMED_EVENTS_LIFECYCLE). Before confirmation nothing changes.
    lifecycle = CONFIRMED_EVENTS_LIFECYCLE

    def __init__(self, basis: str | None = None) -> None:
        # The verified MT5 time basis; None reads TRADING_HUB_MT5_SOURCE_TIMEZONE as main does.
        self._basis = basis

    def basis(self) -> str | None:
        return self._basis if self._basis is not None else os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE")

    def closed_session_context(self, closed: Sequence[dict[str, Any]], basis: str | None) -> dict[str, Any]:
        """Session context from closed M15 bars only, as of the last closed bar's close: its
        close price (not the live price) and its close time (not the wall clock). Without a
        verified basis the bar time is unknown, so the clock is used for the session name
        only; the London range is then unavailable anyway (fail closed, as in v4)."""
        last = closed[-1]
        opened = corrected_bar_time(basis)(last) if basis else None
        as_of = opened + M15 if opened is not None else datetime.now(timezone.utc)
        return compute_session_context(closed, float(last["close"]), as_of, corrected_bar_time(basis) if basis else (lambda row: None))

    def evaluate(self, market: MarketInput) -> dict[str, Any]:
        rows, higher = closed_bars(market.rows), closed_bars(market.higher_rows)
        context = self.closed_session_context(rows, self.basis()) if rows else None
        return scanner.analyze_symbol(market.symbol, rows, spread=market.spread, session_context=context,
                                      higher_rows=higher, strategy_version=self.version, target_model="h1-structure")


SHADOW_STRATEGY_ID = "trendline-first-v5-shadow"


class TrendlineV5ShadowStrategy(TrendlineV5Strategy):
    """trendline-first-v5 under its own strategy_id, for the SHADOW experiment (observational only).
    No longer registered now that v5 is live; kept so its historical records stay reproducible.

    Identical decisions, closed-bar inputs, H1 structural targets and confirmed-events
    lifecycle; only the identity differs, so its records, episodes, confirmations and
    outcomes never mix with the live trendline (v4). The existing SHADOW mode marks
    every record shadow: never a Garden setup, never an alert, never a trade.
    """
    strategy_id = SHADOW_STRATEGY_ID
