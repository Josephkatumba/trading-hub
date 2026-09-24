"""Registry of strategies, their mode and enabled state.

Each registered strategy has a mode (base.LIVE or base.SHADOW) and is enabled
or not. Enabled strategies run; only LIVE ones produce live setups. SHADOW
strategies run and are persisted for review/research, never presented live.

evaluate() runs every ENABLED strategy for one symbol, in registration order,
and isolates them from each other:
  * a strategy that raises yields a failed StrategyResult; the others still run
    and their results are unaffected;
  * a disabled strategy is never called and produces no result;
  * when more than one strategy is enabled, each receives its own copy of the
    market input (bars copied bar by bar), so no strategy can alter another's
    data. (With a single enabled strategy the input is passed as is.)
  * a strategy whose declared data_requirements are missing from the collected
    market context is not run; it yields a failed MissingMarketData result.
    (A MarketInput without collected bars is not checked.)
"""
from __future__ import annotations

import copy
import logging

from .base import DISABLED, LIVE, SHADOW, MarketInput, Strategy, StrategyResult

LOGGER = logging.getLogger("trading_hub.strategies")


class MissingMarketData(Exception):
    """The market context lacks a timeframe the strategy declared it needs."""


def _copy_bars(rows):
    return None if rows is None else [dict(row) for row in rows]


def isolated_copy(market: MarketInput) -> MarketInput:
    """An independent copy of the input: bars are flat dicts, copied one by one
    (much cheaper than deepcopy); the small session context is deep-copied."""
    return MarketInput(market.symbol, _copy_bars(market.rows), market.spread, copy.deepcopy(market.session_context),
                       _copy_bars(market.higher_rows), {tf: _copy_bars(rows) for tf, rows in market.bars.items()},
                       dict(market.unavailable_timeframes))


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}
        self._enabled: set[str] = set()
        self._modes: dict[str, str] = {}

    def register(self, strategy: Strategy, enabled: bool = False, mode: str = LIVE) -> None:
        if strategy.strategy_id in self._strategies:
            raise ValueError(f"strategy {strategy.strategy_id!r} is already registered")
        if mode not in (LIVE, SHADOW):
            raise ValueError(f"unknown strategy mode {mode!r}")
        self._strategies[strategy.strategy_id] = strategy
        self._modes[strategy.strategy_id] = mode
        if enabled:
            self._enabled.add(strategy.strategy_id)

    def enable(self, strategy_id: str) -> None:
        self.get(strategy_id)
        self._enabled.add(strategy_id)

    def disable(self, strategy_id: str) -> None:
        self.get(strategy_id)
        self._enabled.discard(strategy_id)

    def get(self, strategy_id: str) -> Strategy:
        try:
            return self._strategies[strategy_id]
        except KeyError:
            raise KeyError(f"unknown strategy {strategy_id!r}") from None

    def registered(self) -> list[str]:
        return list(self._strategies)

    def enabled(self) -> list[str]:
        """Strategies that run (LIVE and SHADOW)."""
        return [strategy_id for strategy_id in self._strategies if strategy_id in self._enabled]

    def live(self) -> list[str]:
        """Enabled strategies whose setups are presented live."""
        return [strategy_id for strategy_id in self.enabled() if self._modes[strategy_id] == LIVE]

    def mode(self, strategy_id: str) -> str:
        """LIVE / SHADOW for an enabled strategy, DISABLED otherwise (KeyError if unknown)."""
        self.get(strategy_id)
        return self._modes[strategy_id] if strategy_id in self._enabled else DISABLED

    def describe(self) -> list[dict[str, object]]:
        """Registered strategies and their status, for the API/UI (Strategy Lab, filters).

        LIVE strategies produce live setups; SHADOW ones run for review only and
        never produce live Garden setups or alerts; DISABLED ones never run.
        """
        return [{"strategy_id": strategy.strategy_id, "version": strategy.version,
                 "timeframe": strategy.timeframe, "higher_timeframes": list(strategy.higher_timeframes),
                 "status": self.mode(strategy.strategy_id)}
                for strategy in self._strategies.values()]

    def evaluate(self, market: MarketInput) -> dict[str, StrategyResult]:
        enabled = [self._strategies[strategy_id] for strategy_id in self.enabled()]
        shared = len(enabled) == 1
        results: dict[str, StrategyResult] = {}
        for strategy in enabled:
            mode = self._modes[strategy.strategy_id]
            missing = [timeframe for timeframe in strategy.data_requirements
                       if market.bars and timeframe not in market.bars]
            if missing:
                error = MissingMarketData(f"{strategy.strategy_id} needs {', '.join(missing)} for {market.symbol}")
                results[strategy.strategy_id] = StrategyResult(strategy.strategy_id, strategy.version, None, error, mode)
                continue
            try:
                payload = strategy.evaluate(market if shared else isolated_copy(market))
                results[strategy.strategy_id] = StrategyResult(strategy.strategy_id, strategy.version, payload, None, mode)
            except Exception as exc:  # isolation: one strategy's failure is only its own
                LOGGER.warning("Strategy %s failed for %s: %r", strategy.strategy_id, market.symbol, exc)
                results[strategy.strategy_id] = StrategyResult(strategy.strategy_id, strategy.version, None, exc, mode)
        return results
