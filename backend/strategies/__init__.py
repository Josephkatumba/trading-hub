"""Strategy contract, registry and the registered strategies.

Trendline (trendline-first-v5, strategy_id "trendline_v5"), Support & Resistance and
Trend / Momentum are LIVE: each produces its
own setups, lifecycle, confirmations, notifications and outcomes, independently
(scoped by strategy_id). LIVE is not a claim of profitability. SHADOW (research)
mode remains available for future experimental strategies: evaluated and
persisted for review only, never presented as a live setup or alert.
New strategies are added by implementing base.Strategy and
registering them in build_default_registry(); they do not touch the trendline
strategy.
"""
from __future__ import annotations

from .base import (CORE_FIELDS, DISABLED, EVIDENCE_CONTAINER, LEGACY_STRATEGY_ID, LIVE, METADATA_FIELDS, SHADOW,
                   MarketInput, Strategy, StrategyResult, record_strategy_id)
from .registry import StrategyRegistry
from .support_resistance import SupportResistanceStrategy
from .trend_momentum import LegacyTrendMomentumStrategy, TrendMomentumStrategy
from .trendline import (LEGACY_VERSION as TRENDLINE_LEGACY_VERSION, SHADOW_STRATEGY_ID as TRENDLINE_V5_SHADOW,
                        LegacyTrendlineStrategy, TrendlineStrategy, TrendlineV5ShadowStrategy, TrendlineV5Strategy)

# The live trendline: trendline-first-v5 under strategy_id "trendline_v5". The retired
# v4 ("trendline") and v3, and the v5 SHADOW experiment ("trendline-first-v5-shadow"),
# are kept unregistered so their historical records stay reproducible.
TRENDLINE = TrendlineV5Strategy.strategy_id
RETIRED_TRENDLINE = TrendlineStrategy.strategy_id


def build_default_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(TrendlineV5Strategy(), enabled=True, mode=LIVE)
    registry.register(SupportResistanceStrategy(), enabled=True, mode=LIVE)
    registry.register(TrendMomentumStrategy(), enabled=True, mode=LIVE)
    return registry


REGISTRY = build_default_registry()

__all__ = ["CORE_FIELDS", "DISABLED", "EVIDENCE_CONTAINER", "LEGACY_STRATEGY_ID", "LIVE", "METADATA_FIELDS", "MarketInput",
           "REGISTRY", "SHADOW", "Strategy", "StrategyRegistry", "StrategyResult", "SupportResistanceStrategy", "TRENDLINE",
           "TRENDLINE_LEGACY_VERSION", "TRENDLINE_V5_SHADOW", "RETIRED_TRENDLINE", "TrendlineV5ShadowStrategy", "TrendlineV5Strategy", "LegacyTrendMomentumStrategy", "LegacyTrendlineStrategy", "TrendMomentumStrategy", "TrendlineStrategy", "build_default_registry",
           "record_strategy_id"]
