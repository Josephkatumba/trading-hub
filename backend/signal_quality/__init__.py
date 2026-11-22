"""Signal quality: causal market-regime detection, setup features and an evidence-weighted quality grade.

    regime.py    classifies the market (trending / ranging / high- or low-volatility / breakout / reversal)
                 from CLOSED H1 and H4 bars only
    features.py  describes one setup at its entry instant (trend alignment, structure, momentum, volatility,
                 room to the next level, R:R, session, regime) as bucketed categorical features
    model.py     an additive, shrinkage-regularised scorecard fitted on historical cost-aware outcomes; it
                 predicts expectancy in R and maps it to A+ / A / B / C / REJECTED, with regime-compatibility
                 caps and a minimum-evidence rule
    lifecycle.py maps a graded setup to WATCHING -> DETECTED -> DEVELOPING -> CONFIRMING -> CONFIRMED ->
                 ACTIVE -> RESOLVED, so only sufficiently validated setups reach CONFIRMED

Weights are learned from walk-forward historical evidence (research/quality_research.py), never set by hand.
Nothing here places trades or changes execution permissions.
"""
