"""Edge Discovery V2 - pre-registered hypotheses, grids, splits and gates (XAUUSD).

This file is hashed into the ledger BEFORE any result is computed. The runner
refuses to run if the file changes after registration (see runner.py). Every
config below counts as a trial, whether or not it is ever reported.

Prior burden (context for multiple testing): edge-discovery-v1 ran 1,962 trials
(2026-11-22), earlier programs about 227 configs, and scalper tds-1.0 288 configs.
"""
from __future__ import annotations

PROGRAM = "edge-discovery-v2"
SYMBOL = "XAUUSD"
GRID_TF = "M15"   # execution grid; M5 only for the tds-1.0 diagnosis and survivor intrabar checks

# Chronological splits (UTC). Selection happens ONLY inside DEVELOPMENT.
SPLITS = {
    "holdout_early": ("2022-09-01", "2024-09-01"),   # sealed; never used by any prior program
    "development":   ("2024-09-01", "2026-07-01"),   # walk-forward selection lives here
    "holdout_recent": ("2026-07-01", "2026-11-24"),  # sealed; most recent data
}
WALK_FORWARD = {"train_weeks": 26, "test_weeks": 13, "min_train_trades": 20}

COSTS = {
    "spread_floor": 0.08,          # USD/oz; recorded bar spread is used when larger
    "slippage": 0.03,              # USD/oz per market fill (entry, stop, time exit); targets fill at limit
    "commission_rate": 3e-5,       # per side, fraction of notional (cTrader Raw: $3 per $100k)
    "stress_multiplier": 2.0,      # every gate is also checked at 2x all costs
}

# Each hypothesis: mechanism (why it might exist), rules (fixed), grid (the only free parameters).
# The FIRST value of every grid list is the pre-declared default; config 0 = all defaults.
HYPOTHESES = {
    "H1_msb_displacement": {
        "mechanism": "A decisive structure break with a large-body candle signals informed order flow; continuation follows.",
        "grid": {"disp_atr": [1.5, 2.0], "target_r": [2.0, 3.0], "htf_filter": [False, True]},
    },
    "H2_sweep_reversal": {
        "mechanism": "Stops cluster beyond obvious highs/lows; a sweep that closes back inside and breaks the sweep bar shows exhaustion.",
        "grid": {"level": ["prev_day", "asian"], "confirm_bars": [2, 4], "target_r": [2.0, 3.0]},
    },
    "H3_opening_range": {
        "mechanism": "Session opens concentrate institutional order flow; early direction persists through the session.",
        "grid": {"session": ["london", "newyork"], "range_min": [30, 60], "exit": ["2r", "session_close"]},
    },
    "H4_trend_day": {
        "mechanism": "Days that move far early are often driven by persistent flows that continue into the close.",
        "grid": {"decision_ny": ["10:00", "12:00"], "move_adr": [0.5, 0.75], "exit": ["close_16ny", "2r"]},
    },
    "H5_compression_expansion": {
        "mechanism": "Volatility clusters; a breakout from an unusually tight range starts a high-volatility leg.",
        "grid": {"box_width_adr": [0.25, 0.35], "stop": ["opposite", "mid"], "target_r": [2.0, 3.0]},
    },
    "H6_session_gold": {
        "mechanism": "6a: New York often reverses an extended London move in gold. 6b: Asian session is range-bound; stretches revert.",
        "grid": {"variant": ["ny_reverses_london", "asia_fade"], "stretch": [0.5, 0.75], "exit": ["time", "2r"]},
    },
    "H7_news_momentum": {
        "mechanism": "Scheduled US data shocks are absorbed over more than one bar; after the first bar the move continues.",
        "grid": {"shock_atr": [2.0, 3.0], "confirm_bars": [1, 2], "exit": ["time_4h", "2r"]},
        "news_risk": "No entry inside the shock bar; entry only after confirmation and only if spread <= 2x its 20-day median.",
    },
    "H8_failed_breakout": {
        "mechanism": "Breakout traders who entered on a close beyond a level are trapped when price closes back inside; their exits fuel the reversal.",
        "grid": {"level": ["prev_day", "prev_week"], "window": [2, 4], "target": ["2r", "level_mid"]},
    },
}

# Gates. A hypothesis is judged on its walk-forward OOS trades in DEVELOPMENT (gate 1),
# then ONCE on the sealed holdouts with the config selected on the last train window (gate 2).
GATE1 = {
    "min_oos_trades": 40,
    "min_expectancy_r": 0.0,          # after costs, strictly positive
    "min_profit_factor": 1.10,
    "max_p_one_sided": 0.10,          # t-test of mean R > 0
    "min_direction_control_pct": 0.90,  # beats 90% of direction-randomised controls
    "min_share_configs_positive": 0.50,  # parameter robustness on the full development period
}
GATE2 = {
    "each_holdout_expectancy_positive": True,
    "combined_ci95_lower_gt_0": True,   # bootstrap
    "stress_costs_expectancy_positive": True,
    "min_vol_regimes_positive": 2,      # of 3 terciles of causal daily ATR%
    "both_trend_regimes_positive": True,  # sign of trailing 50-day return
    "holm_alpha": 0.05,                 # across all hypotheses that reached gate 2
}
PROMOTION = ("PROMOTED_TO_SHADOW only. Execution stays locked until >= 100 forward shadow signals "
             "show expectancy > 0 and PF > 1.3 (same bar as edge-discovery-v1).")
