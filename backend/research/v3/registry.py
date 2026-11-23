"""TradeDen V3: Information-Driven Quantitative Research. Pre-registered protocol (XAUUSD).

Hashed into backend/data/research/v3/ledger.jsonl BEFORE any result is computed; the runner refuses
to run if this file, projects.py, engine.py or data.py change afterwards.

Prior burden (context for multiple testing, all on gold or including gold):
  edge-discovery-v1 1,962 trials; earlier programs ~227; scalper tds-1.0 288; edge-discovery-v2 448.
"""
from __future__ import annotations

PROGRAM = "tradeden-v3"
SYMBOL = "XAUUSD"

# One cutoff for every project: everything from 2021-01-01 is sealed.
HOLDOUT_START = "2021-01-01"
HOLDOUT_END = "2026-11-24"
HOLDOUT_HALVES = (("2021-01-01", "2024-01-01"), ("2024-01-01", "2026-11-24"))
DEVELOPMENT = {
    "daily":    ("2006-01-01", HOLDOUT_START),   # D1 / weekly horizons (macro daily layer, COT)
    "intraday": ("2016-03-01", HOLDOUT_START),   # H1 / H4 horizons (real intraday gold data starts Feb 2016)
    "regime_d1": ("1999-01-01", HOLDOUT_START),
}
# Expanding-window walk-forward: train on everything before the test year, test one calendar year.
FIRST_TEST_YEAR = {"daily": 2010, "intraday": 2018, "regime_d1": 2005}

COSTS = {
    "spread_floor_bp": 1.5,        # spread = max(recorded, 1.5 bp of price); recorded spread is 0 in old data
    "slippage_bp": 1.0,            # per market fill
    "event_slippage_bp": 3.0,      # entries within 2 h after a release use this instead
    "commission_rate": 3e-5,       # per side, of notional (cTrader Raw, $3 per $100k)
    "financing_markup": 0.008,     # longs pay fed funds + 0.8%/yr, shorts receive fed funds - 0.8%/yr (calibrated
                                   # to IC Markets XAUUSD swap 2026-11: -$0.49/oz long, +$0.33/oz short per night)
    "stress_multiplier": 2.0,
}

# The first value of every grid list is the pre-declared default.
HYPOTHESES = {
    # ------------------------------------------------------------------ PROJECT A: macro gold intelligence
    "A1_usd_reaction_underreaction": {
        "project": "A", "mechanism": "Gold under-reacts to the dollar's response to US macro releases; it keeps moving opposite the USD surprise after the release window.",
        "grid": {"min_abs_z": [1.0, 0.5], "horizon": ["H4", "H1", "D1", "5D"]}},
    "A2_gold_reaction_persistence": {
        "project": "A", "mechanism": "Gold's own release-window move either continues (slow diffusion) or reverts (overshoot). Direction is a selected parameter, so the stability of its sign is what is tested.",
        "grid": {"direction": ["continue", "revert"], "horizon": ["H4", "H1", "D1", "5D"]}},
    "A3_data_surprise_drift": {
        "project": "A", "mechanism": "First-print surprises vs naive expectations (CPI/PCE core MoM vs prior, payrolls vs prior 2-month average, unemployment) are not fully priced on the day; hawkish surprises push gold down for days.",
        "grid": {"min_abs_z": [1.0, 0.5], "horizon": ["D1", "H4", "5D"]}},
    "A4_gold_usd_divergence": {
        "project": "A", "mechanism": "When gold fails to move opposite a USD release reaction, the macro-consistent move follows later.",
        "grid": {"events": ["all", "inflation"], "horizon": ["D1", "H4", "5D"]}},
    "A5_pre_fomc_drift": {
        "project": "A", "mechanism": "Gold drifts up into scheduled FOMC statements (analogue of the equity pre-FOMC drift); long only, exit one hour before the statement.",
        "grid": {"window_h": [24, 48]}},
    "A6_rates_dollar_leadlag": {
        "project": "A", "mechanism": "Daily moves in real yields (FRED DFII10, used with a 1-business-day publication lag) or the dollar proxy lead gold by a day.",
        "grid": {"driver": ["usd_proxy", "real_yield"], "hold": ["1D", "5D"]}},
    # ------------------------------------------------------------------ PROJECT B: positioning and flow
    "B1_cot_extremes_contrarian": {
        "project": "B", "mechanism": "Crowded managed-money positioning (3-year COT index) mean-reverts.",
        "grid": {"band": ["90_10", "80_20"], "hold": ["4W", "1W"]}},
    "B2_cot_mm_flow_momentum": {
        "project": "B", "mechanism": "Speculative flow persists: the direction of managed-money net change predicts the next weeks.",
        "grid": {"change_w": [1, 4], "hold": ["1W", "4W"]}},
    "B3_cot_hedger_flow": {
        "project": "B", "mechanism": "Producers/merchants are informed hedgers: rising net hedger position (short covering) is bullish.",
        "grid": {"change_w": [1, 4], "hold": ["1W", "4W"]}},
    "B4_oi_price_confirmation": {
        "project": "B", "mechanism": "Price trends confirmed by rising open interest (new money) continue.",
        "grid": {"hold": ["4W", "1W"]}},
    "B6_tick_volume_imbalance_proxy": {
        "project": "B", "mechanism": "PROXY ONLY: signed CFD tick-volume imbalance over 24 H1 bars (not exchange volume delta). Direction (follow/fade) is a selected parameter.",
        "grid": {"direction": ["follow", "fade"], "hold": ["H4", "D1"]}},
    # ------------------------------------------------------------------ PROJECT C: regime intelligence
    "C1_regime_conditional": {
        "project": "C", "mechanism": "Standard strategies work only in their natural regime: momentum in trending and in high volatility, mean reversion in ranging, breakouts after low volatility. Regime thresholds are fitted on train folds only; strategy parameters are fixed textbook values.",
        "grid": {"pair": ["MOM|TREND", "MR|RANGE", "BRK|LOWVOL", "MOM|HIGHVOL"], "tf": ["D1", "H4", "H1"]}},
}
DIAGNOSTICS = ["A_event_study_tables", "B5_cot_descriptive_vs_predictive", "C2_regime_persistence"]

GATE1 = {  # development walk-forward out-of-sample (selection on train only)
    "min_trades": 30, "min_mean_r": 0.0, "min_profit_factor": 1.10, "max_p_one_sided": 0.10,
    "min_direction_control_pct": 0.90, "must_beat_benchmark": True, "min_share_configs_positive": 0.50,
}
GATE2 = {  # one shot on the sealed holdout with the config selected on all development data
    "mean_positive": True, "ci95_lower_gt_0": True, "stress_positive": True, "both_halves_positive": True,
    "holm_alpha": 0.05,
}
BENCHMARKS = {
    "directional": "always LONG at the same entries and exits (gold's drift)",
    "long_only": "long at random times with the same holding period (unconditional drift)",
    "regime": "the same strategy traded in every regime (unconditional)",
    "context": "buy-and-hold gold over the evaluation window",
}
PROMOTION = "PROMOTED_TO_SHADOW only; the cBot stays execution-locked (ExecutionUnlocked=false) regardless."
