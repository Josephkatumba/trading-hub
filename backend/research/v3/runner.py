"""TradeDen V3 runner (run from backend/).

    python -m research.v3.runner register      # hash the protocol (once, before any result)
    python -m research.v3.runner develop       # diagnostics + expanding walk-forward in development, gate 1
    python -m research.v3.runner holdout       # ONE-SHOT sealed holdout (2021-01-01 onward) for gate-1 survivors
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
from .engine import Req, always_long, by_year, direction_control, random_time_long, simulate, summarize, t_p
from .projects import GENERATORS, HOLD, Ctx, c1, layer

HERE = Path(__file__).resolve().parent
STATE = HERE.parents[1] / "data" / "research" / "v3"
LEDGER = STATE / "ledger.jsonl"
PROTOCOL_FILES = ("registry.py", "projects.py", "engine.py", "data.py")


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


def rows() -> list[dict]:
    return [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()] if LEDGER.exists() else []


def require_registered() -> str:
    regs = [r for r in rows() if r.get("kind") == "register"]
    if not regs:
        sys.exit("protocol not registered")
    h = protocol_hash()
    if regs[-1]["protocol_sha256"] != h:
        sys.exit("protocol files changed since registration; refusing to run")
    return h


def configs(name: str) -> list[dict]:
    g = reg.HYPOTHESES[name]["grid"]
    return [dict(zip(g, combo)) for combo in itertools.product(*g.values())]


class Study:
    def __init__(self):
        self.ctx = Ctx()
        self._cache: dict = {}

    def reqs(self, name: str, cfg: dict, fit) -> list[Req]:
        key = (name, json.dumps(cfg, sort_keys=True), tuple(fit))
        if key not in self._cache:
            self._cache[key] = GENERATORS[name](self.ctx, cfg, fit)
        return self._cache[key]

    def window(self, reqs: list[Req], start, end) -> list[Req]:
        """Requests decided in [start, end). Development windows may not EXIT inside the sealed holdout."""
        s, e = np.datetime64(start), np.datetime64(end)
        cap = np.datetime64(reg.HOLDOUT_START) if e <= np.datetime64(reg.HOLDOUT_START) else np.datetime64(reg.HOLDOUT_END)
        out = []
        for q in reqs:
            t = self.ctx.s[q.series].t
            if q.x < len(t) and s <= t[q.i] < e and t[q.x] < cap:
                out.append(q)
        return out

    def run(self, reqs: list[Req], cost_mult: float = 1.0) -> tuple[pd.DataFrame, list[Req]]:
        parts, taken = [], []
        for series in sorted({q.series for q in reqs}):
            qs = [q for q in reqs if q.series == series]
            tr = simulate(self.ctx.s[series], qs, cost_mult)
            if not tr.empty:
                parts.append(tr)
                ids = set(tr["i"])
                taken += [q for q in qs if q.i in ids]
        tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        # keep only requests that actually traded (first request per decision bar that was not skipped)
        seen, uniq = set(), []
        for q in sorted(taken, key=lambda q: (q.series, q.i)):
            if (q.series, q.i) not in seen:
                seen.add((q.series, q.i))
                uniq.append(q)
        return tr, uniq


def objective(tr: pd.DataFrame) -> float:
    if tr.empty or len(tr) < 20:
        return -math.inf
    t, _ = t_p(tr["r"].to_numpy(float))
    return t if np.isfinite(t) else -math.inf


def benchmark(study: Study, name: str, cfg: dict, fit, taken: list[Req], tr: pd.DataFrame, start, end) -> dict:
    if tr.empty:
        return {}
    if name.startswith("A5"):
        b = random_time_long(study.ctx.s["H1"], taken, start, end)
        return {"kind": "random_time_long", "mean_r": b.get("mean"), "beaten": tr["r"].mean() > b.get("mean", np.inf)}
    if name.startswith("C1"):
        unc = study.window(c1(study.ctx, cfg, fit, conditional=False), start, end)
        ut, _ = study.run(unc)
        m = float(ut["r"].mean()) if not ut.empty else float("nan")
        return {"kind": "unconditional_strategy", "mean_r": round(m, 4), "beaten": bool(tr["r"].mean() > m)}
    al = always_long(study.ctx.s, taken)
    m = float(al["r"].mean()) if not al.empty else float("nan")
    return {"kind": "always_long_same_timing", "mean_r": round(m, 4), "beaten": bool(tr["r"].mean() > m)}


# ------------------------------------------------------------------ diagnostics (development data only)
def diagnostics(study: Study) -> dict:
    ctx, out = study.ctx, {}
    cut = pd.Timestamp(reg.HOLDOUT_START)
    for lay, ev, s in (("H1", ctx.ev_h1, ctx.s["H1"]), ("D1", ctx.ev_d1, ctx.s["D1"])):
        ev = ev[ev["date"] < cut]
        tab = {}
        for kind, g in ev.groupby("kind"):
            idx = g["i"].to_numpy()
            nxt = (np.log(s.c[np.minimum(idx + (4 if lay == "H1" else 5), s.n - 1)] / s.c[idx]))
            tab[kind] = {"events": int(len(g)),
                         "corr_gold_vs_usd_reaction": round(float(np.corrcoef(g["gold_ret"], g["usd_ret"])[0, 1]), 3),
                         "corr_next_gold_vs_usd_reaction": round(float(np.corrcoef(nxt, g["usd_ret"])[0, 1]), 3),
                         "corr_next_gold_vs_data_surprise": (round(float(pd.Series(nxt).corr(pd.Series(g["data_z"].to_numpy()))), 3)
                                                             if g["data_z"].notna().sum() > 10 else None),
                         "mean_abs_gold_reaction_bp": round(float(np.abs(g["gold_ret"]).mean() * 1e4), 1)}
        out[f"A_event_study_{lay}"] = {"horizon_after_window": "4 H1 bars" if lay == "H1" else "5 days", "by_kind": tab}
    c = ctx.cot[ctx.cot["as_of"] < cut].copy()
    close = ctx.s["D1"].c
    dates = ctx.s["D1"].t
    asof_i = np.searchsorted(dates, c["as_of"].to_numpy(), side="right") - 1
    same = [np.log(close[a] / close[a - 5]) if a >= 5 else np.nan for a in asof_i]
    nxt1 = [np.log(close[min(i + 6, len(close) - 1)] / close[i + 1]) for i in c["i"]]
    nxt4 = [np.log(close[min(i + 21, len(close) - 1)] / close[i + 1]) for i in c["i"]]
    d = c["mm_net"].diff()
    out["B5_cot_descriptive_vs_predictive"] = {
        "weeks": int(d.notna().sum()),
        "corr_mm_change_vs_same_week_gold": round(float(d.corr(pd.Series(same))), 3),
        "corr_mm_change_vs_next_1w_after_release": round(float(d.corr(pd.Series(nxt1))), 3),
        "corr_mm_change_vs_next_4w_after_release": round(float(d.corr(pd.Series(nxt4))), 3),
        "corr_cot_index_vs_next_4w": round(float(c["cot_index"].corr(pd.Series(nxt4))), 3)}
    pers = {}
    for tf in ("D1", "H4", "H1"):
        f = ctx.regime_features(tf)
        dev = ctx.s[tf].t < np.datetime64(reg.HOLDOUT_START)
        er, rv = f["er"].where(dev), f["vol_pct"].where(dev)
        step = slice(None, None, 20)
        pers[tf] = {"er_t_vs_er_t+20_spearman": round(float(er[step].corr(er.shift(-20)[step], method="spearman")), 3),
                    "volpct_t_vs_t+20_spearman": round(float(rv[step].corr(rv.shift(-20)[step], method="spearman")), 3)}
    out["C2_regime_persistence"] = pers
    return out


# ------------------------------------------------------------------ develop
def develop() -> dict:
    h = require_registered()
    study = Study()
    results = {"diagnostics": diagnostics(study)}
    ledger({"kind": "diagnostics", "protocol_sha256": h, "result": results["diagnostics"]})
    for name in reg.HYPOTHESES:
        cfgs = configs(name)
        lays = [layer(name, c) for c in cfgs]
        first = min(reg.FIRST_TEST_YEAR[l] for l in lays)
        oos_parts, oos_taken, oos_stress, folds, bench_rows = [], [], [], [], []
        for year in range(first, 2021):
            te_s, te_e = f"{year}-01-01", f"{year + 1}-01-01"
            scored = []
            for ci, (cfg, lay) in enumerate(zip(cfgs, lays)):
                tr_s = reg.DEVELOPMENT[lay][0]
                if year < reg.FIRST_TEST_YEAR[lay]:
                    continue
                fit = (tr_s, te_s)
                tr, _ = study.run(study.window(study.reqs(name, cfg, fit), tr_s, te_s))
                scored.append((objective(tr), -ci, ci, fit))
                ledger({"kind": "trial", "protocol_sha256": h, "hypothesis": name, "config": ci, "params": cfg,
                        "window": f"train {tr_s}..{te_s}", "summary": summarize(tr)})
            if not scored or max(scored)[0] == -math.inf:
                folds.append({"test_year": year, "selected": None})
                continue
            _, _, best, fit = max(scored)
            cfg = cfgs[best]
            reqs = study.window(study.reqs(name, cfg, fit), te_s, te_e)
            test, taken = study.run(reqs)
            stress, _ = study.run(reqs, reg.COSTS["stress_multiplier"])
            if not test.empty:
                oos_parts.append(test)
                oos_taken += taken
                oos_stress.append(stress)
                bench_rows.append((cfg, fit, taken, test, te_s, te_e))
            folds.append({"test_year": year, "selected": best, "params": cfg, "test": summarize(test)})
            ledger({"kind": "oos", "protocol_sha256": h, "hypothesis": name, "config": best, "params": cfg,
                    "window": f"test {te_s}..{te_e}", "summary": summarize(test)})
        oos = pd.concat(oos_parts, ignore_index=True) if oos_parts else pd.DataFrame()
        s = summarize(oos)
        ctrl = direction_control(study.ctx.s, oos_taken) if oos_taken else {}
        bm = [benchmark(study, name, c, f, tk, ts, a, b) for c, f, tk, ts, a, b in bench_rows]
        if name.startswith("A5") or name.startswith("C1"):
            bm_mean = np.nanmean([x["mean_r"] for x in bm]) if bm else float("nan")
        else:
            al = always_long(study.ctx.s, oos_taken)
            bm_mean = float(al["r"].mean()) if not al.empty else float("nan")
        full = []
        for ci, (cfg, lay) in enumerate(zip(cfgs, lays)):
            dev = reg.DEVELOPMENT[lay]
            tr, _ = study.run(study.window(study.reqs(name, cfg, dev), *dev))
            full.append({"config": ci, "params": cfg, **{k: summarize(tr).get(k) for k in ("trades", "mean_r", "mean_net_bp", "t", "p_one_sided")}})
        share = sum(1 for f in full if (f["mean_r"] or 0) > 0 and (f["trades"] or 0) >= 20) / len(cfgs)
        def full_t(ci):
            f = full[ci]
            ok = (f["trades"] or 0) >= 20 and f["t"] is not None and np.isfinite(f["t"])
            return f["t"] if ok else -1e9
        best_full = max(range(len(cfgs)), key=lambda ci: (full_t(ci), -ci))
        g = reg.GATE1
        checks = {
            "min_trades": s.get("trades", 0) >= g["min_trades"],
            "mean_positive": (s.get("mean_r") or -1) > g["min_mean_r"],
            "profit_factor": (s.get("profit_factor") or 0) >= g["min_profit_factor"],
            "p_value": (s.get("p_one_sided") if s.get("p_one_sided") is not None and np.isfinite(s.get("p_one_sided")) else 1) <= g["max_p_one_sided"],
            "beats_direction_control": bool(ctrl) and (s.get("mean_r") or -9) > ctrl.get("p90", np.inf),
            "beats_benchmark": bool(np.isfinite(bm_mean)) and (s.get("mean_r") or -9) > bm_mean,
            "parameter_robustness": share >= g["min_share_configs_positive"],
        }
        results[name] = {"project": reg.HYPOTHESES[name]["project"], "mechanism": reg.HYPOTHESES[name]["mechanism"],
                         "configs": len(cfgs), "development_full": full, "share_configs_positive": round(share, 3),
                         "folds": folds, "oos": s, "oos_stress_2x": summarize(pd.concat(oos_stress) if oos_stress else pd.DataFrame()),
                         "oos_by_year": by_year(oos), "direction_control": ctrl,
                         "benchmark": {"mean_r": None if not np.isfinite(bm_mean) else round(float(bm_mean), 4),
                                       "kind": bm[0]["kind"] if bm else None},
                         "gate1_checks": checks, "gate1_pass": all(checks.values()),
                         "final_config": best_full, "final_params": cfgs[best_full]}
        ledger({"kind": "gate1", "protocol_sha256": h, "hypothesis": name, "pass": all(checks.values()), "checks": checks, "oos": s})
        print(f"{name:34s} n={s.get('trades', 0):5d} R={s.get('mean_r')} bp={s.get('mean_net_bp')} PF={s.get('profit_factor')} "
              f"p={s.get('p_one_sided')} ctrl90={ctrl.get('p90')} bench={results[name]['benchmark']['mean_r']} cfg+={share:.2f} "
              f"-> {'PASS' if all(checks.values()) else 'fail'}", flush=True)
    (STATE / "develop.json").write_text(json.dumps({"protocol_sha256": h, "generated": now(), "results": results}, indent=1, default=str))
    return results


# ------------------------------------------------------------------ holdout
def holdout() -> dict:
    h = require_registered()
    dev = json.loads((STATE / "develop.json").read_text())
    if dev["protocol_sha256"] != h:
        sys.exit("develop.json is from another protocol version")
    done = {r["hypothesis"] for r in rows() if r.get("kind") == "holdout"}
    study = Study()
    res = {k: v for k, v in dev["results"].items() if k != "diagnostics"}
    survivors = [n for n, r in res.items() if r["gate1_pass"]]
    out = {"survivors": survivors, "results": {}}
    pvals = {}
    for name in survivors:
        if name in done:
            print(name, "already evaluated on the holdout; refusing to re-run")
            continue
        cfg = res[name]["final_params"]
        lay = layer(name, cfg)
        fit = reg.DEVELOPMENT[lay]
        reqs = study.window(study.reqs(name, cfg, fit), reg.HOLDOUT_START, reg.HOLDOUT_END)
        tr, taken = study.run(reqs)
        st, _ = study.run(reqs, reg.COSTS["stress_multiplier"])
        halves = {f"{a}..{b}": summarize(tr[(tr["entry_time"] >= np.datetime64(a)) & (tr["entry_time"] < np.datetime64(b))]) if not tr.empty else {}
                  for a, b in reg.HOLDOUT_HALVES}
        s = summarize(tr)
        ctrl = direction_control(study.ctx.s, taken) if taken else {}
        bm = benchmark(study, name, cfg, fit, taken, tr, reg.HOLDOUT_START, reg.HOLDOUT_END) if not tr.empty else {}
        checks = {"mean_positive": (s.get("mean_r") or -1) > 0,
                  "ci95_lower_gt_0": (s.get("ci95_r") or [-1])[0] > 0,
                  "stress_positive": (summarize(st).get("mean_r") or -1) > 0,
                  "both_halves_positive": all((v.get("mean_r") or -1) > 0 for v in halves.values())}
        pvals[name] = s.get("p_one_sided", 1.0) if s.get("p_one_sided") is not None else 1.0
        out["results"][name] = {"params": cfg, "holdout": s, "halves": halves, "stress_2x": summarize(st),
                                "direction_control": ctrl, "benchmark": bm, "by_year": by_year(tr), "checks": checks}
        ledger({"kind": "holdout", "protocol_sha256": h, "hypothesis": name, "result": out["results"][name]})
    order = sorted(pvals, key=pvals.get)
    m = len(order)
    for rank, name in enumerate(order):
        adj = min(1.0, max(pvals[n] * (m - j) for j, n in enumerate(order[:rank + 1])))
        r = out["results"][name]
        r["holm_p"] = round(adj, 4)
        r["checks"]["holm"] = adj <= reg.GATE2["holm_alpha"]
        r["verdict"] = "PROMOTED_TO_SHADOW" if all(r["checks"].values()) else "REJECTED_AT_HOLDOUT"
        ledger({"kind": "verdict", "protocol_sha256": h, "hypothesis": name, "verdict": r["verdict"], "holm_p": r["holm_p"]})
        print(name, r["verdict"], r["holdout"], flush=True)
    (STATE / "holdout.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def register() -> None:
    h = protocol_hash()
    prior = [r for r in rows() if r.get("kind") == "register"]
    if prior and prior[-1]["protocol_sha256"] == h:
        print("already registered", h)
        return
    ledger({"kind": "register", "program": reg.PROGRAM, "protocol_sha256": h, "files": list(PROTOCOL_FILES),
            "configs": {n: len(configs(n)) for n in reg.HYPOTHESES}, "holdout_start": reg.HOLDOUT_START,
            "note": "registered before any development or holdout result was computed"})
    print("registered", h)


if __name__ == "__main__":
    {"register": register, "develop": develop, "holdout": holdout}[sys.argv[1] if len(sys.argv) > 1 else "develop"]()
