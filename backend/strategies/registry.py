"""Registry of strategies and their enabled state.

evaluate() runs every ENABLED strategy for one symbol, in registration order,
and isolates them from each other:
  * a strategy that raises yields a failed StrategyResult; the others still run
    and their results are unaffected;
  * a disabled strategy is never called and produces no result;
  * when more than one strategy is enabled, each receives its own deep copy of
    the market input, so no strategy can alter another's data. (With a single
    enabled strategy the input is passed as is.)
  * a strategy whose declared data_requirements are missing from the collected
    market context is not run; it yields a failed MissingMarketData result.
    (A MarketInput without collected bars is not checked.)
"""
from __future__ import annotations

import copy
import logging

from .base import MarketInput, Strategy, StrategyResult

LOGGER = logging.getLogger("trading_hub.strategies")


class MissingMarketData(Exception):
    """The market context lacks a timeframe the strategy declared it needs."""


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}
        self._enabled: set[str] = set()

    def register(self, strategy: Strategy, enabled: bool = False) -> None:
        if strategy.strategy_id in self._strategies:
            raise ValueError(f"strategy {strategy.strategy_id!r} is already registered")
        self._strategies[strategy.strategy_id] = strategy
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
        return [strategy_id for strategy_id in self._strategies if strategy_id in self._enabled]

    def describe(self) -> list[dict[str, object]]:
        """Registered strategies and their status, for the API/UI (Strategy Lab, filters).

        LIVE strategies produce live setups; DISABLED ones are registered but never
        run. There is no shadow mode yet: a shadow strategy would be listed with its
        own status and must never produce live Garden setups.
        """
        return [{"strategy_id": strategy.strategy_id, "version": strategy.version,
                 "timeframe": strategy.timeframe, "higher_timeframes": list(strategy.higher_timeframes),
                 "status": "LIVE" if strategy.strategy_id in self._enabled else "DISABLED"}
                for strategy in self._strategies.values()]

    def evaluate(self, market: MarketInput) -> dict[str, StrategyResult]:
        enabled = [self._strategies[strategy_id] for strategy_id in self.enabled()]
        shared = len(enabled) == 1
        results: dict[str, StrategyResult] = {}
        for strategy in enabled:
            missing = [timeframe for timeframe in strategy.data_requirements
                       if market.bars and timeframe not in market.bars]
            if missing:
                error = MissingMarketData(f"{strategy.strategy_id} needs {', '.join(missing)} for {market.symbol}")
                results[strategy.strategy_id] = StrategyResult(strategy.strategy_id, strategy.version, None, error)
                continue
            try:
                payload = strategy.evaluate(market if shared else copy.deepcopy(market))
                results[strategy.strategy_id] = StrategyResult(strategy.strategy_id, strategy.version, payload)
            except Exception as exc:  # isolation: one strategy's failure is only its own
                LOGGER.warning("Strategy %s failed for %s: %r", strategy.strategy_id, market.symbol, exc)
                results[strategy.strategy_id] = StrategyResult(strategy.strategy_id, strategy.version, None, exc)
        return results
