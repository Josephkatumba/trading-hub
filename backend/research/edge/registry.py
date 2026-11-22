"""Pre-registered edge-discovery program: families, parameter grids, exits, splits and gates.

Changing anything here (or in candidates.py) changes the fingerprint; the tournament refuses to run a program
version whose recorded pre-registration fingerprint differs. A new idea therefore needs a new PROGRAM version
and counts as additional trials in the multiple-testing record.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc
PROGRAM = "edge-discovery-v1"
TARGETS = ("XAUUSD", "BTCUSD", "ETHUSD", "NAS100", "US500", "GER40")
CONTROL_UNIVERSE = ("XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY")
SPLITS = {
    "train": (datetime(2024, 10, 15, tzinfo=UTC), datetime(2025, 10, 1, tzinfo=UTC)),
    "validation": (datetime(2025, 10, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC)),
    "test": (datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 10, 12, tzinfo=UTC)),
}
OOS_QUARTERS = [datetime(2025, 10, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC),
                datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 10, 12, tzinfo=UTC)]
EXITS = ("natural", "1.5R", "2R", "3R", "trail", "partial", "time")
GATES = {
    "min_train_trades": 60, "min_validation_trades": 30, "min_test_trades": 30, "credible_oos_trades": 100,
    "validation_pf": 1.1, "test_pf": 1.1, "holm_alpha": 0.10, "random_seeds": 20, "random_percentile": 95,
    "quarters_positive": 3,
}

FAMILIES: list[dict[str, Any]] = [
    # A. market microstructure
    {"key": "stop_hunt_pdhl", "group": "A microstructure", "natural": "target",
     "theory": "Stop orders cluster beyond the previous day's extremes (Osler 2003); a sweep that closes back inside "
               "has exhausted that liquidity and tends to revert.",
     "configs": [{"depth": 0.0}, {"depth": 0.25}, {"depth": 0.5}]},
    {"key": "failed_asian_breakout", "group": "A microstructure", "natural": "target",
     "theory": "London breakouts of the Asian range that fail trap breakout traders; their exits push price back across the range.",
     "configs": [{"n": 2}, {"n": 4}, {"n": 8}]},
    {"key": "displacement_pullback", "group": "A microstructure", "natural": None,
     "theory": "A displacement candle reveals one-sided order flow (an imbalance); a shallow first pullback is absorbed by it.",
     "configs": [{"k": k, "tf": tf} for tf in ("M15", "M30", "H1") for k in (1.5, 2.0, 2.5)]},
    # B. statistical
    {"key": "anchored_mean_reversion", "group": "B statistical", "natural": "target",
     "theory": "Liquidity providers absorb temporary imbalances; without a trend, large deviations from the day's "
               "average traded price partly revert. (Tick-weighted proxy: no exchange volume available.)",
     "configs": [{"k": 1.5}, {"k": 2.0}, {"k": 2.5}]},
    {"key": "volatility_expansion", "group": "B statistical", "natural": None,
     "theory": "Volatility clusters: low volatility is followed by expansion, and the first range escape sets its direction.",
     "configs": [{"tf": "M30"}, {"tf": "H1"}, {"tf": "H4"}]},
    {"key": "tsmom", "group": "B statistical", "natural": None,
     "theory": "Time-series momentum from slow information diffusion and trend-following flows (Moskowitz, Ooi & Pedersen 2012).",
     "configs": [{"tf": tf, "L": L} for tf in ("H1", "H4") for L in (20, 55)]},
    {"key": "large_move", "group": "B statistical", "natural": "time",
     "theory": "Return autocorrelation after large moves is market specific (continuation from information, reversal from "
               "liquidity shocks); the direction is taken from the TRAIN-period structure only.",
     "configs": [{"tf": "M15"}, {"tf": "M30"}, {"tf": "H1"}]},
    # C. session
    {"key": "opening_range_breakout", "group": "C session", "natural": "time",
     "theory": "Overnight information is priced at the cash open; the opening range breakout follows the dominant early order flow.",
     "configs": [{"minutes": 15}, {"minutes": 30}, {"minutes": 60}]},
    {"key": "intraday_momentum", "group": "C session", "natural": "time",
     "theory": "Early-session returns predict the last half hour to hour (Gao, Han, Li & Zhou 2018): late informed and "
               "hedging flows trade in the direction of the open.",
     "configs": [{"minutes": 30}, {"minutes": 60}, {"minutes": 300}]},
    {"key": "london_compression_breakout", "group": "C session", "natural": "time",
     "theory": "A quiet Asian session leaves orders resting at its range; London liquidity breaks it with follow-through.",
     "configs": [{"q": 0.4}, {"q": 0.6}, {"q": 0.8}]},
    {"key": "overlap_continuation", "group": "C session", "natural": "time",
     "theory": "A strong London move continues into the London/New York overlap as US participants join the trend.",
     "configs": [{"k": 0.3}, {"k": 0.5}, {"k": 0.7}]},
    {"key": "london_exhaustion_fade", "group": "C session", "natural": "target",
     "theory": "An extended London move is partly reversed at the New York open as European positions are closed.",
     "configs": [{"k": 0.6}, {"k": 0.8}, {"k": 1.0}]},
    # D. price action
    {"key": "pdhl_break_retest", "group": "D price action", "natural": None,
     "theory": "A break of the previous day's extreme that holds on its retest marks acceptance at new prices.",
     "configs": [{"n": 4}, {"n": 8}, {"n": 16}]},
    {"key": "pwhl_reaction", "group": "D price action", "natural": None,
     "theory": "Previous-week extremes are widely watched: rejection (fade) or acceptance (continuation).",
     "configs": [{"mode": "fade"}, {"mode": "fade_wick"}, {"mode": "continue"}]},
]
# E. quantitative layer (built from the base families inside the tournament; fixed designs, no grid)
QUANT = {
    "regime_selector": "per instrument, map each regime to the base family with the best TRAIN expectancy in it "
                       "(>= 30 train trades in that regime, E > 0); trade only those (family, regime) pairs",
    "ensemble_2of_n": "take a base-family signal only if a DIFFERENT family signalled the same direction within the "
                      "previous 4 M15 bars (causal agreement), exit 2R",
    "logit_h1": "per-instrument L2 logistic regression on H1 features (4 return lags, EMA20/50 distance, RSI, ADX, ATR "
                "ratio, hour) predicting the 4-bar return sign; trained on train only; trade p > 0.56 / < 0.44, stop 1 ATR",
}


def spec() -> dict[str, Any]:
    from research.edge import candidates
    return {"program": PROGRAM, "targets": TARGETS, "control_universe": CONTROL_UNIVERSE,
            "splits": {k: [v[0].isoformat(), v[1].isoformat()] for k, v in SPLITS.items()},
            "exits": EXITS, "gates": GATES, "families": FAMILIES, "quant": QUANT,
            "candidates_source_sha256": hashlib.sha256(inspect.getsource(candidates).encode()).hexdigest()}


def fingerprint() -> str:
    return hashlib.sha256(json.dumps(spec(), sort_keys=True, default=str).encode()).hexdigest()


def trial_count() -> int:
    """Configuration x exit trials per instrument in the base grid (for the multiple-testing record)."""
    return sum(len(f["configs"]) * len(EXITS) for f in FAMILIES)
