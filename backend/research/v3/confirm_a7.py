"""TradeDen V3.1: ONE confirmatory test on the sealed holdout (registered before running).

Origin (disclosed): the V3 development diagnostics showed gold continuing AGAINST the dollar's FOMC-day reaction
(corr -0.35 over 5 days, n=73). An exploration on DEVELOPMENT data only (ledger kind "exploration") tried three
variants; the 1-day hold was strongest (+0.46R, t 2.9, n 73, 2011-2020). That is a post-hoc selection from about
4,000 cumulative trials, so development evidence is NOT counted; only this one-shot holdout test decides.

Rule A7 (single config, no parameters):
  On each scheduled FOMC statement day (federalreserve.gov list), at the D1 close (17:00 New York), take the
  sign of the USD-proxy change for that broker day; trade gold in the OPPOSITE direction at the next D1 open,
  exit at the following D1 open (one day). Costs, financing and fills: research/v3/engine.py unchanged.
Gate: research/v3/registry.py GATE2 (mean > 0, bootstrap CI95 lower > 0, 2x costs > 0, both holdout halves > 0),
  plus beating random-direction controls (p90) and always-long at the same timing. Holm m = 1.

    python -m research.v3.confirm_a7 register
    python -m research.v3.confirm_a7 run        (refuses to run twice)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import registry as reg
from .engine import Req, always_long, by_year, direction_control, summarize
from .runner import HERE, STATE, Study, ledger, now, rows

FILES = ("confirm_a7.py", "registry.py", "projects.py", "engine.py", "data.py")
ID = "A7_fomc_dollar_continuation_1d"


def phash() -> str:
    h = hashlib.sha256()
    for f in FILES:
        h.update(f.encode())
        h.update((HERE / f).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def requests(study: Study, start: str, end: str) -> list[Req]:
    ev = study.ctx.ev_d1
    f = ev[(ev["kind"] == "FOMC") & (ev["date"] >= start) & (ev["date"] < end)]
    return [Req("D1", int(e.i), int(e.i) + 2, -int(np.sign(e.usd_ret))) for e in f.itertuples() if e.usd_ret != 0]


def register() -> None:
    h = phash()
    if any(r.get("kind") == "register_v3.1" and r["protocol_sha256"] == h for r in rows()):
        print("already registered", h)
        return
    ledger({"kind": "register_v3.1", "program": "tradeden-v3.1-confirmatory", "hypothesis": ID, "protocol_sha256": h,
            "files": list(FILES), "note": "single pre-declared rule, one-shot on the sealed holdout 2021-01-01..2026-11-24"})
    print("registered", h)


def run() -> dict:
    h = phash()
    regs = [r for r in rows() if r.get("kind") == "register_v3.1"]
    if not regs or regs[-1]["protocol_sha256"] != h:
        sys.exit("V3.1 not registered or files changed since registration")
    if any(r.get("kind") == "holdout_v3.1" for r in rows()):
        sys.exit("V3.1 holdout already evaluated; refusing to re-run")
    study = Study()
    reqs = study.window(requests(study, reg.HOLDOUT_START, reg.HOLDOUT_END), reg.HOLDOUT_START, reg.HOLDOUT_END)
    tr, taken = study.run(reqs)
    st, _ = study.run(reqs, reg.COSTS["stress_multiplier"])
    s = summarize(tr)
    halves = {f"{a}..{b}": summarize(tr[(tr["entry_time"] >= np.datetime64(a)) & (tr["entry_time"] < np.datetime64(b))])
              for a, b in reg.HOLDOUT_HALVES}
    ctrl = direction_control(study.ctx.s, taken)
    al = always_long(study.ctx.s, taken)
    bench = float(al["r"].mean()) if not al.empty else float("nan")
    dev_tr, _ = study.run(study.window(requests(study, "2011-01-01", reg.HOLDOUT_START), "2011-01-01", reg.HOLDOUT_START))
    checks = {"mean_positive": (s.get("mean_r") or -1) > 0, "ci95_lower_gt_0": (s.get("ci95_r") or [-1])[0] > 0,
              "stress_positive": (summarize(st).get("mean_r") or -1) > 0,
              "both_halves_positive": all((v.get("mean_r") or -1) > 0 for v in halves.values()),
              "beats_direction_control": (s.get("mean_r") or -9) > ctrl.get("p90", np.inf),
              "beats_always_long": (s.get("mean_r") or -9) > bench,
              "holm": (s.get("p_one_sided") or 1) <= reg.GATE2["holm_alpha"]}
    verdict = "PROMOTED_TO_SHADOW" if all(checks.values()) else "REJECTED_AT_HOLDOUT"
    out = {"id": ID, "protocol_sha256": h, "generated": now(), "rule": __doc__.split("Rule A7")[1].split("Gate:")[0].strip(),
           "development_in_sample_not_counted": summarize(dev_tr), "holdout": s, "halves": halves, "stress_2x": summarize(st),
           "direction_control": ctrl, "always_long_mean_r": round(bench, 4), "by_year": by_year(tr), "checks": checks,
           "verdict": verdict, "trades": tr.assign(entry_time=tr["entry_time"].astype(str), exit_time=tr["exit_time"].astype(str)).to_dict("records") if not tr.empty else []}
    ledger({"kind": "holdout_v3.1", "protocol_sha256": h, "hypothesis": ID, "verdict": verdict, "holdout": s, "checks": checks})
    (STATE / "confirm_a7.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("holdout", "halves", "stress_2x", "direction_control", "always_long_mean_r", "checks", "verdict")}, indent=1, default=str))
    return out


if __name__ == "__main__":
    {"register": register, "run": run}[sys.argv[1]]()
