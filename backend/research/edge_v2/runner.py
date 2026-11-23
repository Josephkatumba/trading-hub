"""Edge Discovery V2 runner.

    python -m research.edge_v2.runner register     # hash the protocol into the ledger (once)
    python -m research.edge_v2.runner develop      # walk-forward inside DEVELOPMENT, gate 1
    python -m research.edge_v2.runner holdout      # ONE-SHOT sealed holdouts for gate-1 survivors

Run from backend/. Every evaluated (hypothesis, config, window) is appended to the ledger.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import registry as reg
from .data import load
from .engine import Book, Signal, simulate, summarize, by, t_p, bootstrap_ci
from .hypotheses import GENERATORS, Ctx

HERE = Path(__file__).resolve().parent
STATE = HERE.parents[1] / "data" / "research" / "edge_v2"
LEDGER = STATE / "ledger.jsonl"
PROTOCOL_FILES = ("registry.py", "hypotheses.py", "engine.py", "data.py")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def protocol_hash() -> str:
    h = hashlib.sha256()
    for f in PROTOCOL_FILES:
        h.update(f.encode())
        h.update((HERE / f).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def ledger(rec: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now(), **rec}, default=str) + "\n")


def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]


def require_registered() -> str:
    regs = [r for r in ledger_rows() if r.get("kind") == "register"]
    if not regs:
        sys.exit("protocol not registered: run `register` first")
    h = protocol_hash()
    if regs[-1]["protocol_sha256"] != h:
        sys.exit("protocol files changed since registration; refusing to run (re-register as a NEW protocol version)")
    return h


def configs(name: str) -> list[dict]:
    g = reg.HYPOTHESES[name]["grid"]
    keys = list(g)
    return [dict(zip(keys, combo)) for combo in itertools.product(*(g[k] for k in keys))]


def window_signals(sigs: list[Signal], utc: np.ndarray, start: str, end: str) -> list[Signal]:
    s, e = np.datetime64(start), np.datetime64(end)
    return [x for x in sigs if s <= utc[x.i] < e]


def weeks(start: str, n: int) -> str:
    return str((pd.Timestamp(start) + pd.Timedelta(weeks=n)).date())


def folds() -> list[tuple[str, str, str, str]]:
    d0, d1 = reg.SPLITS["development"]
    tw, sw = reg.WALK_FORWARD["train_weeks"], reg.WALK_FORWARD["test_weeks"]
    out, k = [], 0
    while True:
        tr_s = weeks(d0, k * sw)
        tr_e = weeks(tr_s, tw)
        te_e = min(weeks(tr_e, sw), d1)
        if tr_e >= d1:
            break
        out.append((tr_s, tr_e, tr_e, te_e))
        k += 1
    return out


def objective(tr: pd.DataFrame) -> float:
    if tr.empty or len(tr) < reg.WALK_FORWARD["min_train_trades"]:
        return -math.inf
    t, _ = t_p(tr["r"].to_numpy(float))
    return t if not math.isnan(t) else -math.inf


class Study:
    def __init__(self):
        self.df = load(reg.GRID_TF)
        self.book = Book(self.df)
        self.ctx = Ctx(self.df)
        self.utc = self.df["utc"].to_numpy()
        self._sig: dict = {}

    def signals(self, name: str, cfg: dict) -> list[Signal]:
        key = (name, json.dumps(cfg, sort_keys=True))
        if key not in self._sig:
            self._sig[key] = GENERATORS[name](self.ctx, **cfg)
        return self._sig[key]

    def run(self, name: str, cfg: dict, start: str, end: str, cost_mult: float = 1.0) -> pd.DataFrame:
        return simulate(self.book, window_signals(self.signals(name, cfg), self.utc, start, end), cost_mult)


def pooled_direction_control(study: Study, parts: list[tuple[list[Signal], pd.DataFrame]], seeds: int = 200) -> dict:
    actual = np.concatenate([t["r"].to_numpy(float) for _, t in parts if not t.empty]) if parts else np.array([])
    if len(actual) == 0:
        return {}
    means = []
    for seed in range(seeds):
        rng = np.random.default_rng(1000 + seed)
        rs = []
        for sigs, trades in parts:
            if trades.empty:
                continue
            taken = set(trades["i"])
            ctrl = []
            for s in sigs:
                if s.i not in taken:
                    continue
                c = study.book.c[s.i]
                dist = abs(c - s.stop)
                side = int(rng.choice([-1, 1]))
                tr_r = s.target_r if s.target_r else (abs(s.target - c) / dist if s.target is not None and dist > 0 else None)
                ctrl.append(Signal(s.i, side, c - side * dist, None, tr_r, s.exit_idx))
            sim = simulate(study.book, ctrl)
            if not sim.empty:
                rs.append(sim["r"].to_numpy(float))
        if rs:
            means.append(np.concatenate(rs).mean())
    means = np.array(means)
    return {"seeds": int(len(means)), "control_mean": round(float(means.mean()), 4),
            "control_p90": round(float(np.quantile(means, 0.9)), 4),
            "strategy_percentile": round(float((means < actual.mean()).mean()), 3)}


def develop() -> dict:
    h = require_registered()
    study = Study()
    d0, d1 = reg.SPLITS["development"]
    fl = folds()
    results = {}
    for name in reg.HYPOTHESES:
        cfgs = configs(name)
        full = []
        for ci, cfg in enumerate(cfgs):
            tr = study.run(name, cfg, d0, d1)
            s = summarize(tr)
            full.append({"config": ci, "params": cfg, **{k: s.get(k) for k in ("trades", "expectancy_r", "profit_factor", "t", "p_one_sided")}})
            ledger({"kind": "trial", "protocol_sha256": h, "hypothesis": name, "config": ci, "params": cfg,
                    "window": "development_full", "summary": s})
        oos_parts, oos_stress, fold_rows = [], [], []
        for tr_s, tr_e, te_s, te_e in fl:
            scored = []
            for ci, cfg in enumerate(cfgs):
                tr = study.run(name, cfg, tr_s, tr_e)
                scored.append((objective(tr), -ci, ci))
                ledger({"kind": "trial", "protocol_sha256": h, "hypothesis": name, "config": ci, "params": cfg,
                        "window": f"train {tr_s}..{tr_e}", "summary": summarize(tr)})
            best_obj, _, best = max(scored)
            row = {"train": [tr_s, tr_e], "test": [te_s, te_e]}
            if best_obj == -math.inf:
                row["selected"] = None
                fold_rows.append(row)
                continue
            cfg = cfgs[best]
            sigs = window_signals(study.signals(name, cfg), study.utc, te_s, te_e)
            test = simulate(study.book, sigs)
            oos_parts.append((sigs, test))
            oos_stress.append(simulate(study.book, sigs, reg.COSTS["stress_multiplier"]))
            row.update({"selected": best, "params": cfg, "train_t": round(best_obj, 2), "test": [te_s, te_e],
                        "test_summary": summarize(test)})
            fold_rows.append(row)
            ledger({"kind": "oos", "protocol_sha256": h, "hypothesis": name, "config": best, "params": cfg,
                    "window": f"test {te_s}..{te_e}", "summary": summarize(test)})
        oos = pd.concat([t for _, t in oos_parts if not t.empty], ignore_index=True) if oos_parts else pd.DataFrame()
        stress = pd.concat([t for t in oos_stress if not t.empty], ignore_index=True) if oos_stress else pd.DataFrame()
        s_oos = summarize(oos)
        control = pooled_direction_control(study, oos_parts) if not oos.empty else {}
        share_pos = sum(1 for f in full if (f["expectancy_r"] or 0) > 0 and (f["trades"] or 0) >= 20) / len(cfgs)
        default_oos = pd.concat([study.run(name, cfgs[0], te_s, te_e) for _, _, te_s, te_e in fl], ignore_index=True)
        # final selection for the holdout: best on the last train-length window of development
        last_s = weeks(d1, -reg.WALK_FORWARD["train_weeks"])
        final = max(((objective(study.run(name, c, last_s, d1)), -ci, ci) for ci, c in enumerate(cfgs)))[2]
        g = reg.GATE1
        checks = {
            "min_oos_trades": s_oos.get("trades", 0) >= g["min_oos_trades"],
            "expectancy_positive": (s_oos.get("expectancy_r") or -1) > g["min_expectancy_r"],
            "profit_factor": (s_oos.get("profit_factor") or 0) >= g["min_profit_factor"],
            "p_value": (s_oos.get("p_one_sided") if s_oos.get("p_one_sided") is not None else 1) <= g["max_p_one_sided"],
            "beats_direction_control": (control.get("strategy_percentile") or 0) >= g["min_direction_control_pct"],
            "parameter_robustness": share_pos >= g["min_share_configs_positive"],
        }
        results[name] = {
            "mechanism": reg.HYPOTHESES[name]["mechanism"],
            "configs": len(cfgs), "development_full": full, "share_configs_positive": round(share_pos, 3),
            "folds": fold_rows, "oos": s_oos, "oos_stress_2x": summarize(stress), "oos_default_config": summarize(default_oos),
            "oos_by_session": by(oos, "session"), "oos_by_side": by(oos, "side"), "oos_by_reason": by(oos, "reason"),
            "oos_by_year": by(oos.assign(year=pd.to_datetime(oos["entry_utc"]).dt.year) if not oos.empty else oos, "year"),
            "direction_control": control, "gate1_checks": checks, "gate1_pass": all(checks.values()),
            "final_config": final, "final_params": cfgs[final],
        }
        ledger({"kind": "gate1", "protocol_sha256": h, "hypothesis": name, "pass": all(checks.values()), "checks": checks,
                "oos": s_oos, "final_config": final})
        print(f"{name:28s} OOS n={s_oos.get('trades',0):4d} E={s_oos.get('expectancy_r')} PF={s_oos.get('profit_factor')} "
              f"p={s_oos.get('p_one_sided')} ctrl%={control.get('strategy_percentile')} cfg+={share_pos:.2f} -> "
              f"{'PASS' if all(checks.values()) else 'fail'}", flush=True)
    out = STATE / "develop.json"
    out.write_text(json.dumps({"protocol_sha256": h, "generated": now(), "folds": fl, "results": results}, indent=1, default=str))
    return results


def regime_tags(study: Study, tr: pd.DataFrame, vol_edges: tuple[float, float]) -> pd.DataFrame:
    adr = study.df["adr20"].to_numpy() / study.df["close"].to_numpy()
    ret = study.df["ret50"].to_numpy()
    v = adr[tr["i"].to_numpy()]
    tr = tr.copy()
    tr["vol_regime"] = np.where(v <= vol_edges[0], "low", np.where(v <= vol_edges[1], "mid", "high"))
    tr["trend_regime"] = np.where(ret[tr["i"].to_numpy()] >= 0, "up", "down")
    return tr


def holdout() -> dict:
    h = require_registered()
    dev = json.loads((STATE / "develop.json").read_text())
    if dev["protocol_sha256"] != h:
        sys.exit("develop.json is from another protocol version")
    done = {r["hypothesis"] for r in ledger_rows() if r.get("kind") == "holdout"}
    study = Study()
    d0, d1 = reg.SPLITS["development"]
    dmask = (study.df["utc"] >= d0) & (study.df["utc"] < d1)
    vol = (study.df["adr20"] / study.df["close"])[dmask].dropna()
    edges = (float(vol.quantile(1 / 3)), float(vol.quantile(2 / 3)))   # fixed on development, never on holdout
    survivors = [n for n, r in dev["results"].items() if r["gate1_pass"]]
    out = {"survivors": survivors, "vol_edges_from_development": edges, "results": {}}
    pvals = {}
    for name in survivors:
        if name in done:
            print(f"{name}: holdout already evaluated; refusing to re-run")
            continue
        cfg = dev["results"][name]["final_params"]
        parts = {}
        for split in ("holdout_early", "holdout_recent"):
            a, b = reg.SPLITS[split]
            tr = regime_tags(study, study.run(name, cfg, a, b), edges)
            st = study.run(name, cfg, a, b, reg.COSTS["stress_multiplier"])
            parts[split] = (tr, st)
        both = pd.concat([p[0] for p in parts.values()], ignore_index=True)
        stress = pd.concat([p[1] for p in parts.values()], ignore_index=True)
        s = summarize(both)
        vol_by = by(both, "vol_regime")
        trend_by = by(both, "trend_regime")
        g = reg.GATE2
        checks = {
            "each_holdout_positive": all((summarize(p[0]).get("expectancy_r") or -1) > 0 for p in parts.values()),
            "combined_ci95_lower_gt_0": (s.get("ci95") or [-1])[0] > 0,
            "stress_costs_positive": (summarize(stress).get("expectancy_r") or -1) > 0,
            "vol_regimes_positive": sum(1 for v in vol_by.values() if (v.get("expectancy_r") or -1) > 0) >= g["min_vol_regimes_positive"],
            "both_trend_regimes_positive": len(trend_by) == 2 and all((v.get("expectancy_r") or -1) > 0 for v in trend_by.values()),
        }
        pvals[name] = s.get("p_one_sided", 1.0)
        out["results"][name] = {"params": cfg, "holdout_early": summarize(parts["holdout_early"][0]),
                                "holdout_recent": summarize(parts["holdout_recent"][0]), "combined": s,
                                "stress_2x": summarize(stress), "by_vol_regime": vol_by, "by_trend_regime": trend_by,
                                "by_session": by(both, "session"), "checks": checks}
        ledger({"kind": "holdout", "protocol_sha256": h, "hypothesis": name, "params": cfg, "result": out["results"][name]})
    # Holm across hypotheses that reached gate 2
    order = sorted(pvals, key=pvals.get)
    m = len(order)
    for rank, name in enumerate(order):
        adj = min(1.0, max(pvals[n] * (m - k) for k, n in enumerate(order[:rank + 1])))
        r = out["results"][name]
        r["holm_p"] = round(adj, 4)
        r["checks"]["holm"] = adj <= reg.GATE2["holm_alpha"]
        r["verdict"] = "PROMOTED_TO_SHADOW" if all(r["checks"].values()) else "REJECTED_AT_HOLDOUT"
        ledger({"kind": "verdict", "protocol_sha256": h, "hypothesis": name, "verdict": r["verdict"], "holm_p": r["holm_p"]})
        print(name, r["verdict"], r["combined"], flush=True)
    (STATE / "holdout.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def register() -> None:
    h = protocol_hash()
    prior = [r for r in ledger_rows() if r.get("kind") == "register"]
    if prior and prior[-1]["protocol_sha256"] == h:
        print("already registered", h)
        return
    ledger({"kind": "register", "program": reg.PROGRAM, "protocol_sha256": h, "files": list(PROTOCOL_FILES),
            "configs": {n: len(configs(n)) for n in reg.HYPOTHESES}, "splits": reg.SPLITS,
            "note": "registered before any development or holdout result was computed"})
    print("registered", h)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "develop"
    {"register": register, "develop": develop, "holdout": holdout}[cmd]()
