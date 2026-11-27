"""Edge discovery laboratory (TRADEDEN V2). See docs/EDGE_DISCOVERY_PLAN.md for the pre-registered protocol.

    market.py       causal per-instrument arrays: M15 base, M30/H1/H4 aggregates, ATR, session clocks,
                    previous-day / previous-week levels, Asian range
    diagnostics.py  experiment 0: autocorrelation, variance ratios, large-move continuation, time of day
    registry.py     the pre-registered candidate families, their parameter grids and exits (hashed)
    candidates.py   causal signal generators for every family
    tournament.py   train selection -> validation gate (Holm, random controls) -> one-shot test -> leaderboard,
                    adaptive selector, ensemble, classifier, benchmarks; every trial recorded in the ledger

Run:  python -m research.edge.tournament
"""
