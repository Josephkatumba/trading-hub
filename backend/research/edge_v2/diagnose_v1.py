"""Why did scalper tds-1.0 have ~0R gross expectancy? (development data only)

Runs the frozen tds-1.0 signal logic (ctrader_scalper/engine/strategy.py) on XAUUSD M5
from 2025-06-26 to 2026-07-01 (the V2 development window; no holdout data) and measures:
  1. signed forward return after each signal, in ATR, at 5 min .. 4 h, vs controls;
  2. the move that happened BEFORE the signal (are entries late?);
  3. MFE / MAE geometry vs the 1.5R target / 1R stop;
  4. whether the quality score or its components rank outcomes;
  5. M5 return structure (autocorrelation, variance ratios, post-shock drift);
  6. the cost hurdle in ATR and R.
Note: M5 bars stand in for M1 in build_frames, so the M1 spike filter is evaluated on M5 bars.

    python -m research.edge_v2.diagnose_v1      (from backend/)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ctrader_scalper"))
from engine.strategy import generate_candidates  # noqa: E402  (frozen tds-1.0 logic)

from .data import BARS, wilder  # noqa: E402
from .registry import COSTS, SPLITS  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "data" / "research" / "edge_v2" / "diagnose_v1.json"
HORIZONS = [1, 3, 6, 12, 24, 48]


def tstat(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return None
    return round(float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))), 2)


def stat(x):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return {"n": int(len(x)), "mean": round(float(x.mean()), 4) if len(x) else None, "t": tstat(x)}


def main():
    m5 = pd.read_csv(BARS / "XAUUSD_M5.csv.gz", parse_dates=["utc"])
    m5 = m5[m5["utc"] < SPLITS["development"][1]].reset_index(drop=True)
    m5 = m5.rename(columns={"utc": "time"})
    m5["spread_px"] = np.maximum(m5["spread"] * 0.01, COSTS["spread_floor"])
    frame = m5[["time", "open", "high", "low", "close", "spread_px"]]
    cands = generate_candidates("XAUUSD", frame)

    t = m5["time"].to_numpy()
    o, h, l, c = (m5[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    prev = np.r_[c[0], c[:-1]]
    atr = wilder(np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev))), 14)
    k = np.searchsorted(t, cands["time"].to_numpy(), side="left")     # entry bar (next open)
    ok = (k + max(HORIZONS) < len(t)) & (k >= 13)
    cands, k = cands[ok].reset_index(drop=True), k[ok]
    side = cands["side"].to_numpy()
    a = cands["atr"].to_numpy()
    entry = o[k]

    res = {"window": [str(m5["time"].iloc[0]), SPLITS["development"][1]], "signals": int(len(cands)),
           "by_setup_counts": cands["setup"].value_counts().to_dict()}

    # 1. forward signed returns (mid-ish, before costs) in ATR
    fwd = {hz: (c[k + hz - 1] - entry) * side / a for hz in HORIZONS}
    res["forward_return_atr"] = {f"{hz * 5}min": stat(v) for hz, v in fwd.items()}
    # controls: (a) same bars, random direction; (b) all session bars in the trend direction of EMA9/21
    rng = np.random.default_rng(0)
    rs = rng.choice([-1, 1], len(k))
    res["control_random_direction_atr"] = {f"{hz * 5}min": stat((c[k + hz - 1] - entry) * rs / a) for hz in HORIZONS}
    ema = lambda x, n: pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()
    trend = np.sign(ema(c, 9) - ema(c, 21))
    allk = np.arange(300, len(t) - 50, 3)
    res["control_every_bar_trend_follow_atr"] = {f"{hz * 5}min": stat((c[allk + hz] - o[allk + 1]) * trend[allk] / atr[allk]) for hz in HORIZONS}

    # 2. pre-signal move (chasing?)
    pre6 = (c[k - 1] - c[k - 7]) * side / a
    pre12 = (c[k - 1] - c[k - 13]) * side / a
    res["pre_signal_move_atr"] = {"30min": stat(pre6), "60min": stat(pre12)}
    q = pd.qcut(pre12, 4, labels=["Q1 small", "Q2", "Q3", "Q4 large"])
    res["forward60_by_prior_move_quartile"] = {str(g): stat(fwd[12][q == g]) for g in q.categories}

    # 3. MFE / MAE over 2 h in ATR
    mfe = np.array([((h[j:j + 24].max() - entry[n]) if side[n] > 0 else (entry[n] - l[j:j + 24].min())) / a[n] for n, j in enumerate(k)])
    mae = np.array([((entry[n] - l[j:j + 24].min()) if side[n] > 0 else (h[j:j + 24].max() - entry[n])) / a[n] for n, j in enumerate(k)])
    stop_atr = np.abs(cands["ref"].to_numpy() - (cands["anchor"].to_numpy() - side * 0.3 * a)) / a
    res["excursion_2h_atr"] = {"mfe": stat(mfe), "mae": stat(mae), "median_stop_distance_atr": round(float(np.median(stop_atr)), 3),
                               "share_mfe_reaching_1p5R": round(float((mfe >= 1.5 * stop_atr).mean()), 3),
                               "share_mae_reaching_1R": round(float((mae >= stop_atr).mean()), 3)}

    # 4. does the score rank outcomes?
    res["forward60_by_score"] = {str(b): stat(fwd[12][(cands["score"] >= lo) & (cands["score"] < hi)])
                                 for b, (lo, hi) in {"<70": (0, 70), "70-79": (70, 80), "80-89": (80, 90), "90+": (90, 101)}.items()}
    comps = [col for col in cands.columns if col.startswith("s_")]
    res["component_spearman_vs_forward60"] = {col[2:]: round(float(pd.Series(cands[col]).rank().corr(pd.Series(fwd[12]).rank())), 3) for col in comps}
    res["forward60_by_setup"] = {s: stat(fwd[12][cands["setup"].to_numpy() == s]) for s in ("BRT", "PB")}

    # 5. return structure of gold M5 (development window)
    r = np.diff(np.log(c))
    res["m5_structure"] = {
        "lag1_autocorr": round(float(np.corrcoef(r[:-1], r[1:])[0, 1]), 4),
        "variance_ratio": {q_: round(float(np.var(pd.Series(np.log(c)).diff(q_).dropna()) / (q_ * np.var(r))), 3) for q_ in (2, 4, 12, 48)},
    }
    z = (r - pd.Series(r).rolling(288).mean().to_numpy()) / pd.Series(r).rolling(288).std().to_numpy()
    nxt = np.r_[r[1:], np.nan]
    nxt6 = pd.Series(r).rolling(6).sum().shift(-6).to_numpy()
    big = np.abs(z) > 2.5
    res["m5_structure"]["after_2p5sigma_bar"] = {"n": int(big.sum()), "next_bar_signed_bp": round(float(np.nanmean(np.sign(r[big]) * nxt[big]) * 1e4), 2),
                                                 "next_30min_signed_bp": round(float(np.nanmean(np.sign(r[big]) * nxt6[big]) * 1e4), 2)}

    # 6. cost hurdle
    price = c[k]
    cost = cands["spread"].to_numpy() + 2 * COSTS["slippage"] + 2 * COSTS["commission_rate"] * price
    res["cost_hurdle"] = {"round_trip_cost_atr_median": round(float(np.median(cost / a)), 3),
                          "round_trip_cost_R_median": round(float(np.median(cost / (stop_atr * a))), 3),
                          "atr_usd_median": round(float(np.median(a)), 3)}
    OUT.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
