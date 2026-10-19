"""TRADEden autonomous strategy-discovery workflow and qualification registry (T-033).

Pipeline for every library entry (research/library.py):
  1 intake       data available?  -> otherwise ARCHIVED ("data unavailable" / blocked infrastructure)
  2 dedupe       fingerprint(key, grid, protocol, data window) already evaluated -> skip (no rework)
  3 implement    a registered candidate grid (CANDIDATES) or an imported prior result (V6 rounds)
  4 train        rank the grid on TRAIN (robust shortlist; v6.select)       -> RESEARCHING
  5 validation   choose one configuration on VALIDATION                     -> BACKTESTED or ARCHIVED
  6 test         score the chosen configuration ONCE on TEST (enforced: a configuration can never
                 consume the test window twice)                               -> VALIDATED / BACKTESTED / ARCHIVED
  7 controls     random-entry control on development; global Holm-Bonferroni across every
                 test-scored configuration ever (V6 + T-033)
  8 rank/report  ranked by out-of-sample evidence; data/research/discovery_report.md
Statuses: DISCOVERED -> RESEARCHING -> BACKTESTED -> VALIDATED -> FORWARD_TESTING -> PRODUCTION_CANDIDATE,
or ARCHIVED (with reason). FORWARD_TESTING and PRODUCTION_CANDIDATE are set only by `promote`, which
records the CEO approval reference; the workflow never promotes on its own.

    python -m research.discovery run [KEY ...]     evaluate pending library entries
    python -m research.discovery status            registry table
    python -m research.discovery report            write the ranked report
    python -m research.discovery promote KEY STATUS --approval "CEO approval reference"
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from research import lab, library, v6

PROTOCOL = "train2024-10-15/valid2025-10-01/test2026-04-01..2026-10-12;costs=v6;select=v6.select"
STATUSES = ("DISCOVERED", "RESEARCHING", "BACKTESTED", "VALIDATED", "FORWARD_TESTING", "PRODUCTION_CANDIDATE", "ARCHIVED")


def registry_path() -> Path:
    return lab.root() / "registry.json"


def load() -> dict[str, Any]:
    p = registry_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"strategies": {}, "test_consumed": {}, "global": {}}


def save(reg: dict[str, Any]) -> None:
    registry_path().parent.mkdir(parents=True, exist_ok=True)
    tmp = registry_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
    # OneDrive (and antivirus) can hold the target briefly on Windows: retry the atomic replace.
    import time
    for attempt in range(20):
        try:
            tmp.replace(registry_path())
            return
        except PermissionError:
            time.sleep(0.25 * (attempt + 1))
    raise PermissionError(f"could not replace {registry_path()} (file locked)")


def set_status(reg: dict[str, Any], key: str, status: str, note: str, **fields: Any) -> None:
    assert status in STATUSES
    entry = reg["strategies"].setdefault(key, {"history": []})
    entry.update(status=status, note=note, **fields)
    entry["history"].append({"at": datetime.now(timezone.utc).isoformat(), "status": status, "note": note})


def fingerprint(key: str, configs: list[str]) -> str:
    manifest = (lab.root() / "bars" / "manifest.json")
    window = json.loads(manifest.read_text(encoding="utf-8")).get("end", "") if manifest.exists() else ""
    return hashlib.sha256(json.dumps([key, sorted(configs), PROTOCOL, window[:10]]).encode()).hexdigest()[:16]


# ----- candidate grids (small, pre-registered; library key -> grid) ---------------------------------------

def _grid() -> dict[str, dict[str, Any]]:
    from research import candidates as c
    gen = v6.generate
    return {
        "supertrend": {"grid": {f"{tf}, k={k}": (lambda tf=tf, k=k: gen(lambda h: c.supertrend(h, tf, k)))
                                for tf in ("H1", "H4") for k in (2.0, 3.0)}},
        "intraday_momentum": {"grid": {f"{v}, stop {s} ATR": (lambda v=v, s=s: gen(lambda h: c.intraday_momentum(h, v, s)))
                                       for v in ("gao", "late") for s in (1.0, 2.0)}},
        "rsi2": {"grid": {f"{tf}, stop {s} ATR": (lambda tf=tf, s=s: gen(lambda h: c.rsi2(h, tf, s)))
                          for tf in ("H1", "D1") for s in (2.0, 3.0)}},
        "nr7": {"grid": {f"stop {m}, exit {e}": (lambda m=m, e=e: gen(lambda h: c.nr7(h, m, e)))
                         for m in ("far", "mid") for e in ("day", "2R")}},
        "williams_vb": {"grid": {f"k={k}, {'trend' if t else 'no filter'}": (lambda k=k, t=t: gen(lambda h: c.volatility_breakout(h, k, t)))
                                 for k in (0.3, 0.5, 0.7) for t in (True, False)}},
        "fx_local_hours": {"grid": {f"legs {g}, stop {s} ATR": (lambda g=g, s=s: gen(lambda h: c.fx_local_hours(h, g, s)))
                                    for g in ("eu", "us", "asia", "all") for s in (2.0,)}},
        "turn_of_month": {"grid": {f"stop {s} ATR": (lambda s=s: gen(lambda h: c.turn_of_month(h, s))) for s in (2.0, 3.0)}},
        "overnight_drift": {"grid": {f"stop {s} ATR": (lambda s=s: gen(lambda h: c.overnight_drift(h, s))) for s in (1.5, 3.0)}},
        "vsa_climax": {"grid": {f"volume x{m}, target {r}R": (lambda m=m, r=r: gen(lambda h: c.volume_climax(h, m, r)))
                                for m in (3.0, 5.0) for r in (1.5, 2.0)}},
        "ml_logit": {"grid": {f"threshold {t}": (lambda t=t: c.logit_model().signals(t)) for t in (0.55, 0.60, 0.65)},
                     "selection": "validation_only",
                     "note": "TRAIN is the model's fitting data (in-sample), so the threshold is chosen on VALIDATION only."},
    }


def _prior_results() -> dict[str, dict[str, Any]]:
    """V6 rounds 1-3 imported as completed evaluations (same protocol)."""
    out = {}
    v = json.loads((lab.root() / "v6_results.json").read_text(encoding="utf-8")) if (lab.root() / "v6_results.json").exists() else {}
    r3 = json.loads((lab.root() / "v6_round3_results.json").read_text(encoding="utf-8")) if (lab.root() / "v6_round3_results.json").exists() else {}
    fin = {**v.get("finalists", {}), **v.get("finalists_round2", {})}
    families = {"tsmom": "D1 time-series momentum (weekly)", "ma_breakout_brock": "Donchian H1 trend breakout",
                "turtle": "H4 Donchian + D1 trend", "orb": "London opening-range breakout", "bollinger_mr": "H1 Bollinger mean reversion",
                "squeeze": "H1 volatility squeeze breakout"}
    for key, fam in families.items():
        sel = v.get("selections", {}).get(fam)
        if not sel:
            continue
        f = fin.get(fam)
        out[key] = {"family": fam, "configs": len(sel["train"]), "chosen": sel["chosen"],
                    "validation": sel["validation"].get(sel["chosen"]) if sel["chosen"] else None,
                    "test": f["test"] if f else None, "verdict": f["verdict"] if f else
                    ("REJECTED ON VALIDATION" if sel["shortlist"] else "REJECTED ON TRAIN")}
    for key, fam in (("xsmom_fx", "Cross-sectional momentum (weekly)"), ("inside_bar", "H4 inside-bar breakout")):
        e = r3.get("families", {}).get(fam)
        if e:
            out[key] = {"family": fam, "configs": len(e["train"]), "chosen": e["chosen"],
                        "validation": e["validation"].get(e["chosen"]) if e["chosen"] else None,
                        "test": (e.get("test") or {}).get("test"), "verdict": (e.get("test") or {}).get("verdict") or
                        ("REJECTED ON VALIDATION" if e["shortlist"] else "REJECTED ON TRAIN")}
    if r3.get("hybrid"):
        out["regime_switch"] = {"family": "regime-aware hybrid", "configs": 1, "chosen": "train rule",
                                "validation": r3["hybrid"].get("validation"), "test": r3["hybrid"].get("test"),
                                "verdict": "REJECTED ON VALIDATION" if not r3["hybrid"].get("test") else "SCORED"}
    out["smc_ict"] = {"family": "production SMC / SMC V2", "configs": 7, "chosen": "as deployed",
                      "validation": (v.get("selections", {}).get("SMC (production)") or {}).get("validation", {}).get("as deployed"),
                      "test": (fin.get("SMC (production)") or {}).get("test"), "verdict": "FAILED ON TEST"}
    return out


def _status_from_verdict(verdict: str) -> tuple[str, str]:
    if verdict.startswith("CREDIBLE"):
        return "VALIDATED", "credible improvement on the single test scoring; ready for a forward-test proposal"
    if verdict.startswith("PROMISING"):
        return "BACKTESTED", "test positive but not significant / not robust; forward test only with CEO approval"
    return "ARCHIVED", verdict.lower()


# ----- evaluation -------------------------------------------------------------------------------------------

def _validation_only(key: str, spec: dict[str, Any]) -> dict[str, Any]:
    built = {name: b() for name, b in spec["grid"].items()}
    train = {n: v6.stats(v6.run(s, v6.TRAIN), v6.TRAIN) for n, s in built.items()}
    valid = {n: v6.stats(v6.run(s, v6.VALID), v6.VALID) for n, s in built.items()}
    for n in built:
        lab.record({"name": f"T033 {key}: {n}", "kind": "t033-train", "family": key, "config": n,
                    "train_in_sample": train[n], "validation": valid[n], "verdict": "validation-only selection"})
    ok = [n for n in built if valid[n]["trades"] >= v6.MIN_VALID and (valid[n]["expectancy_r"] or 0) > 0]
    chosen = max(ok, key=lambda n: valid[n]["expectancy_r"]) if ok else None
    return {"family": key, "configs_tried": len(built), "train": train, "shortlist": list(built), "validation": valid,
            "chosen": chosen, "chosen_validation_positive": bool(chosen), "_signals": built}


def evaluate(reg: dict[str, Any], key: str, spec: dict[str, Any], log: Callable[[str], None]) -> None:
    fp = fingerprint(key, list(spec["grid"]))
    entry = reg["strategies"].get(key, {})
    if entry.get("fingerprint") == fp:
        log(f"  {key}: already evaluated with this protocol and data (fingerprint {fp}); skipped")
        return
    set_status(reg, key, "RESEARCHING", f"evaluating {len(spec['grid'])} pre-registered configurations")
    save(reg)
    if spec.get("selection") == "validation_only":
        sel = _validation_only(key, spec)
    else:
        sel = v6.select(key, {"grid": spec["grid"], "rationale": library.get(key)["rationale"]}, log)
    result: dict[str, Any] = {"configs": len(spec["grid"]), "train": sel["train"], "shortlist": sel["shortlist"],
                              "chosen": sel["chosen"], "validation": sel["validation"].get(sel["chosen"]) if sel["chosen"] else None}
    if not sel["shortlist"]:
        verdict = "REJECTED ON TRAIN"
    elif not sel["chosen_validation_positive"]:
        verdict = "REJECTED ON VALIDATION"
    else:
        consumed_key = f"{key}::{sel['chosen']}"
        if consumed_key in reg["test_consumed"]:
            raise RuntimeError(f"{consumed_key} has already been scored on the test window; refusing to score it again")
        scored = v6.score_test(sel)
        reg["test_consumed"][consumed_key] = datetime.now(timezone.utc).isoformat()
        verdict = v6.verdict(scored)
        test_rs = [t["r"] for t in scored["_test_trades"] if t["r"] is not None]
        from research.v6_round3 import one_sided_p
        result.update(test={k: v for k, v in scored.items() if not k.startswith("_")}, p_value=one_sided_p(test_rs))
        result["random_control"] = random_percentile(sel["_signals"][sel["chosen"]])
        lab.record({"name": f"T033 FINALIST {key}: {sel['chosen']}", "kind": "t033-test", "family": key,
                    **{k: v for k, v in scored.items() if not k.startswith("_")}, "verdict": verdict})
    result["verdict"] = verdict
    status, note = _status_from_verdict(verdict) if verdict not in ("REJECTED ON TRAIN", "REJECTED ON VALIDATION") \
        else ("ARCHIVED", verdict.lower())
    set_status(reg, key, status, note, fingerprint=fp, result=result, evaluated_by="T-033 discovery workflow")
    save(reg)
    log(f"  {key}: {verdict}")


def random_percentile(signals: list[dict[str, Any]], seeds: int = 10) -> dict[str, Any]:
    window = (v6.TRAIN[0], v6.VALID[1])
    sig = [s for s in signals if window[0].timestamp() <= s["utc"] < window[1].timestamp() and s.get("take_profit") is not None]
    if not sig:
        return {"note": "no fixed-target development signals to mirror"}
    from research.metrics import summarize
    actual = summarize(v6.run(sig, window))["expectancy_r"]
    draws = sorted(summarize(v6.run(v6.random_twins(sig, s), window))["expectancy_r"] for s in range(seeds))
    return {"strategy": actual, "random_median": draws[len(draws) // 2], "percentile": round(sum(d < actual for d in draws) / seeds, 2)}


def global_multiple_testing(reg: dict[str, Any]) -> dict[str, Any]:
    from research.v6_round3 import holm
    pvals = {}
    r3 = json.loads((lab.root() / "v6_round3_results.json").read_text(encoding="utf-8")) if (lab.root() / "v6_round3_results.json").exists() else {}
    pvals.update({f"V6 {k}": v for k, v in r3.get("multiple_testing", {}).get("raw_one_sided_p", {}).items()})
    for key, e in reg["strategies"].items():
        p = (e.get("result") or {}).get("p_value")
        if p is not None:
            pvals[f"T033 {key}"] = p
    out = {"tests": len(pvals), "raw": {k: round(v, 4) for k, v in pvals.items()}, "holm": holm(pvals) if pvals else {}}
    reg["global"]["multiple_testing"] = out
    return out


def run(keys: list[str] | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    reg = load()
    grids = _grid()
    priors = _prior_results()
    for e in library.LIBRARY:
        key = e["key"]
        if keys and key not in keys:
            continue
        ok, why = library.available(e)
        current = reg["strategies"].get(key, {})
        if e.get("note_only"):
            if current.get("status") != "ARCHIVED":
                set_status(reg, key, "ARCHIVED", "methodology note, not a strategy")
            continue
        if not ok:
            if current.get("note") != why:
                set_status(reg, key, "ARCHIVED", why)
            continue
        if key in grids:
            evaluate(reg, key, grids[key], log)
        elif key in priors:
            if current.get("result") != priors[key]:
                status, note = _status_from_verdict(priors[key]["verdict"]) if priors[key]["verdict"] not in (
                    "REJECTED ON TRAIN", "REJECTED ON VALIDATION") else ("ARCHIVED", priors[key]["verdict"].lower())
                set_status(reg, key, status, note + " (V6 research, imported)", result=priors[key], evaluated_by="V6 rounds 1-3")
        elif not current:
            set_status(reg, key, "DISCOVERED", e.get("deprioritised") or "awaiting implementation")
        save(reg)
    global_multiple_testing(reg)
    save(reg)
    return reg


def promote(key: str, status: str, approval: str) -> None:
    if status not in ("FORWARD_TESTING", "PRODUCTION_CANDIDATE"):
        raise SystemExit("promote only to FORWARD_TESTING or PRODUCTION_CANDIDATE")
    if not approval.strip():
        raise SystemExit("an approval reference is required")
    reg = load()
    current = reg["strategies"].get(key, {}).get("status")
    allowed = {"FORWARD_TESTING": ("BACKTESTED", "VALIDATED"), "PRODUCTION_CANDIDATE": ("FORWARD_TESTING",)}[status]
    if current not in allowed:
        raise SystemExit(f"{key} is {current}; {status} requires one of {allowed}")
    set_status(reg, key, status, f"promoted with approval: {approval}")
    save(reg)


# ----- ranking and report -----------------------------------------------------------------------------------

def ranked(reg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    holm = reg["global"].get("multiple_testing", {}).get("holm", {})
    order = {"VALIDATED": 0, "BACKTESTED": 1, "RESEARCHING": 2, "ARCHIVED": 3, "DISCOVERED": 4}

    def score(item):
        key, e = item
        r = e.get("result") or {}
        test = (r.get("test") or {}).get("test", r.get("test")) or {}
        val = r.get("validation") or {}
        return (order.get(e.get("status"), 9), holm.get(f"T033 {key}", 1.0),
                -(test.get("expectancy_r") if test.get("expectancy_r") is not None else -9),
                -(val.get("expectancy_r") if val and val.get("expectancy_r") is not None else -9))
    return sorted(reg["strategies"].items(), key=score)


def report(reg: dict[str, Any] | None = None, path: Path | None = None) -> Path:
    reg = reg or load()
    path = path or lab.root() / "discovery_report.md"
    mt = reg["global"].get("multiple_testing", {})
    lines = ["# TRADEden strategy discovery: ranked research report", "",
             f"Generated {datetime.now(timezone.utc).isoformat()[:16]} UTC by `python -m research.discovery report`.",
             f"Protocol: {PROTOCOL}. Test-scored configurations across all research: {mt.get('tests', 0)} (Holm-Bonferroni below).", "",
             "| Rank | Strategy | Status | Configs | Chosen config | Validation E (n) | Test E (95% CI), n | Holm p | Note |",
             "|---|---|---|---|---|---|---|---|---|"]
    holm = mt.get("holm", {})
    for rank, (key, e) in enumerate(ranked(reg), 1):
        name = library.get(key)["name"] if any(x["key"] == key for x in library.LIBRARY) else key
        r = e.get("result") or {}
        test = (r.get("test") or {}).get("test", r.get("test")) or {}
        val = r.get("validation") or {}
        hp = holm.get(f"T033 {key}") or next((p for k, p in holm.items() if r.get("family") and r["family"] in k), None)
        lines.append(f"| {rank} | {name} | {e.get('status')} | {r.get('configs', '–')} | {r.get('chosen') or '–'} | "
                     f"{'%+.3f (%s)' % (val['expectancy_r'], val['trades']) if val and val.get('expectancy_r') is not None else '–'} | "
                     f"{'%+.3f (%+.2f, %+.2f), %s' % (test['expectancy_r'], test['expectancy_ci95'][0], test['expectancy_ci95'][1], test['trades']) if test.get('expectancy_r') is not None else '–'} | "
                     f"{hp if hp is not None else '–'} | {e.get('note', '')} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    args = sys.argv[1:] or ["status"]
    if args[0] == "run":
        reg = run(args[1:] or None, lambda m: print(m, flush=True))
        print(report(reg))
    elif args[0] == "report":
        print(report())
    elif args[0] == "promote":
        approval = args[args.index("--approval") + 1] if "--approval" in args else ""
        promote(args[1], args[2], approval)
    else:
        for key, e in ranked(load()):
            print(f"{key:20} {e.get('status', ''):14} {e.get('note', '')[:90]}")


if __name__ == "__main__":
    main()
