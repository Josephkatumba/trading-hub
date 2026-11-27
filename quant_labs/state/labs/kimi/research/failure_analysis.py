"""Phase 1 failure analysis: why did the three Kimi families lose?

Uses the frozen evaluator's own trade records (local replications) and recomputes
path excursions (MFE/MAE) from the shared dataset. Research only; no level of
this analysis touches model parameters.
"""
import bisect
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))
from quant_labs.data import SharedData
from quant_labs.evaluation.v1.engine import epoch, POLICY

DATASET = "bf130602dca4f955f64160bc9b85f0bc4246195f9685afbde91d1856c2c62cd3"
RUNS = ["lsr_v010_full", "lsr_v020_full", "ord_v010_full", "ord_v020_full",
        "vef_v010_full", "vef_v020_full"]
VAL = epoch(POLICY["validation_start"])
TEST = epoch(POLICY["test_start"])
END = epoch(POLICY["test_end"])


def period_of(t):
    return "train" if t < VAL else ("validation" if t < TEST else "test")


def weekday(t):
    return ((int(t) // 86400) + 4) % 7


def load_frames(ds, symbol):
    m15 = [b for b in ds.read(symbol, "M15") if b["utc"] + 900 <= END]
    h1 = [b for b in ds.read(symbol, "H1") if b["utc"] + 3600 <= END]
    return m15, h1


def h1_er(h1, times, t):
    i = bisect.bisect_left(times, t - 3600)
    if i < 10:
        return None
    net = abs(h1[i]["close"] - h1[i - 10]["close"])
    path = sum(abs(h1[j]["close"] - h1[j - 1]["close"]) for j in range(i - 9, i + 1))
    return net / path if path > 0 else 1.0


def mfe_mae(m15, times, plan, exit_at):
    i = bisect.bisect_left(times, plan["entry_at"])
    long = plan["direction"] == "LONG"
    risk = plan["risk"]
    entry = plan["entry"]
    mfe = mae = 0.0
    while i < len(m15) and m15[i]["utc"] < exit_at:
        b = m15[i]
        if long:
            mfe = max(mfe, (b["high"] - entry) / risk)
            mae = min(mae, (entry - b["low"]) / risk)
        else:
            mfe = max(mfe, (entry - b["low"]) / risk)
            mae = min(mae, (b["high"] - entry) / risk)
        i += 1
    return mfe, mae


def main():
    ds = SharedData(str(REPO / "quant_labs" / "state" / "shared"), DATASET)
    frames = {}
    analysis = {}
    for tag in RUNS:
        result = json.loads((Path(__file__).parent / "results" / tag / "local_result.json").read_text())
        fam = tag.rsplit("_v0", 1)[0]
        for tr in result["trades"]:
            p = tr["plan"]
            n = tr["normal"]
            symbol = p["symbol"]
            if symbol not in frames:
                m15, h1 = load_frames(ds, symbol)
                frames[symbol] = (m15, h1, [b["utc"] for b in m15], [b["utc"] for b in h1])
            m15, h1, t15, th1 = frames[symbol]
            at = p["entry_at"]
            per = period_of(at)
            key = (fam, "0.2.0" if "v020" in tag else "0.1.0", per)
            row = analysis.setdefault(key, {"n": 0, "statuses": {}, "rs": [], "mfes": [], "maes": [],
                                            "cost_r": [], "hours": {}, "dows": {}, "ers": {}, "closed": 0})
            row["n"] += 1
            row["statuses"][n["status"]] = row["statuses"].get(n["status"], 0) + 1
            if n.get("r") is not None:
                row["rs"].append(n["r"])
                row["closed"] += 1
                exit_at = n["exit_at"]
                mfe, mae = mfe_mae(m15, t15, p, exit_at)
                row["mfes"].append(round(mfe, 2))
                row["maes"].append(round(mae, 2))
                spread = p["entry_spread"]
                exit_slip = 0.5 * spread if n["status"] == "SL" else 0.25 * spread
                cost = (0.25 * spread + exit_slip + POLICY["commission_price"][symbol]) / p["risk"]
                cost += abs(n.get("financing_price", 0.0)) / p["risk"]
                row["cost_r"].append(cost)
                hr = (int(at) // 3600) % 24
                row["hours"].setdefault(hr, []).append(n["r"])
                row["dows"].setdefault(weekday(at), []).append(n["r"])
                er = h1_er(h1, th1, at)
                if er is not None:
                    bucket = "0-0.2" if er < 0.2 else "0.2-0.4" if er < 0.4 else "0.4-0.6" if er < 0.6 else "0.6+"
                    row["ers"].setdefault(bucket, []).append(n["r"])
    out = {}
    for (fam, ver, per), row in sorted(analysis.items()):
        rs = row["rs"]
        mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
        out[f"{fam}:{ver}:{per}"] = {
            "attempted": row["n"], "resolved": row["closed"],
            "statuses": row["statuses"], "expR": mean(rs),
            "cost_R_avg": mean(row["cost_r"]),
            "mfe_avg": mean(row["mfes"]), "mae_avg": mean(row["maes"]),
            "sl_mfe_avg": None, "tp_mae_avg": None,
            "by_hour": {str(h): {"n": len(v), "expR": mean(v)} for h, v in sorted(row["hours"].items())},
            "by_dow": {str(d): {"n": len(v), "expR": mean(v)} for d, v in sorted(row["dows"].items())},
            "by_er": {b: {"n": len(v), "expR": mean(v)} for b, v in sorted(row["ers"].items())},
        }
    # refine: MFE for SL trades / MAE for TP trades
    Path(__file__).parent.joinpath("results/failure_analysis.json").write_text(json.dumps(out, indent=1))

    # regime-shift diagnostic: H1 ER by period per symbol
    regime = {}
    for symbol, (m15, h1, t15, th1) in sorted(frames.items()):
        for per, lo, hi in (("train", epoch(POLICY["train_start"]), VAL),
                            ("validation", VAL, TEST), ("test", TEST, END)):
            ers = []
            i = bisect.bisect_left(th1, lo)
            while i < len(h1) and h1[i]["utc"] < hi:
                er = h1_er(h1, th1, h1[i]["utc"] + 3600)
                if er is not None:
                    ers.append(er)
                i += 24  # sample every 24 H1 bars
            if ers:
                regime.setdefault(symbol, {})[per] = {"mean_ER": round(sum(ers) / len(ers), 3),
                                                      "frac_ER<0.3": round(sum(1 for e in ers if e < 0.3) / len(ers), 3),
                                                      "n": len(ers)}
    Path(__file__).parent.joinpath("results/regime_by_period.json").write_text(json.dumps(regime, indent=1))

    for k, v in out.items():
        print(f"{k}: n={v['resolved']} expR={v['expR']} costR={v['cost_R_avg']} "
              f"mfe={v['mfe_avg']} mae={v['mae_avg']} statuses={v['statuses']}")
    print()
    for s, periods in regime.items():
        print(s, {p: periods[p]["mean_ER"] for p in ("train", "validation", "test") if p in periods})


if __name__ == "__main__":
    main()
