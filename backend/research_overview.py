"""Unified research overview: every TradeDen research program, read-only, from archived evidence files.

GET /api/research/overview  (local owner view only)
Nothing here computes or re-runs research; it only reads frozen JSON outputs and the cBot's execution lock.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
V3_STATE = REPO / "backend" / "data" / "research" / "v3"
CBOT = REPO / "ctrader_scalper" / "cbot" / "TradeDenScalper.cs"

router = APIRouter()


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _count_lines(path: Path, kinds: tuple[str, ...]) -> int:
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            if json.loads(line).get("kind") in kinds:
                n += 1
        except json.JSONDecodeError:
            continue
    return n


def cbot_lock() -> dict:
    try:
        src = CBOT.read_text(encoding="utf-8")
    except OSError:
        return {"found": False}
    unlocked = re.search(r"ExecutionUnlocked\s*=\s*(true|false)", src)
    verdict = re.search(r'ResearchVerdict\s*=\s*"([^"]*)"', src)
    return {"found": True, "execution_unlocked": unlocked is not None and unlocked.group(1) == "true",
            "research_verdict": verdict.group(1) if verdict else None}


def edge_v1() -> dict:
    t = _load(DOCS / "edge-discovery-v1-tournament-2026-11-22.json") or {}
    trials = t.get("trials", {})
    gold = next((r for r in t.get("leaderboard", []) if str(r.get("instrument", r.get("symbol", ""))) == "XAUUSD"), None)
    return {"id": "edge-discovery-v1", "date": "2026-11-22", "scope": "6 markets, M15-H4, 14 families + 21 existing strategies",
            "trials": trials.get("configuration_x_exit_trials"), "status_counts": t.get("status_counts"),
            "verdict": "NO_EDGE", "report": "docs/EDGE_DISCOVERY_REPORT.md", "best_gold_row": gold}


def scalper_v1() -> dict:
    folder = DOCS / "scalper-v1-evidence-2026-11-23"
    rep = _load(folder / "walkforward_XAUUSD_BTCUSD_EURUSD_GBPUSD_20261123T1713Z.json") or {}
    return {"id": "scalper-tds-1.0", "date": "2026-11-23", "scope": "EMA/RSI/ATR scalper, M5, 4 symbols",
            "trials": sum(s.get("configs_tested", 0) for s in rep.get("symbols", [])) or None,
            "symbols": [{"symbol": s["symbol"], "verdict": s.get("verdict"), "oos": s.get("out_of_sample")} for s in rep.get("symbols", [])],
            "portfolio_oos": (rep.get("portfolio_oos") or {}).get("summary"), "verdict": "NO_EDGE",
            "report": "ctrader_scalper/README.md#results"}


def edge_v2() -> dict:
    dev = _load(DOCS / "edge-discovery-v2-develop-2026-11-23.json") or {}
    hold = _load(DOCS / "edge-discovery-v2-holdout-2026-11-23.json") or {}
    hyps = []
    for name, r in (dev.get("results") or {}).items():
        h = (hold.get("results") or {}).get(name)
        hyps.append({"id": name, "oos": r.get("oos"), "gate1_pass": r.get("gate1_pass"),
                     "holdout": (h or {}).get("combined"), "verdict": (h or {}).get("verdict") or ("REJECTED_AT_GATE1" if not r.get("gate1_pass") else None)})
    return {"id": "edge-discovery-v2", "date": "2026-11-23", "scope": "8 gold price/session/news models, M15",
            "trials": _count_lines(DOCS / "edge-discovery-v2-ledger-2026-11-23.jsonl", ("trial",)),
            "hypotheses": hyps, "verdict": "NO_EDGE", "report": "docs/EDGE_DISCOVERY_V2_REPORT.md"}


def v3() -> dict:
    dev = _load(V3_STATE / "develop.json") or _load(DOCS / "tradeden-v3-develop-2026-11-23.json") or {}
    hold = _load(V3_STATE / "holdout.json") or _load(DOCS / "tradeden-v3-holdout-2026-11-23.json") or {}
    res = dev.get("results") or {}
    hyps = []
    for name, r in res.items():
        if name == "diagnostics":
            continue
        h = (hold.get("results") or {}).get(name)
        verdict = (h or {}).get("verdict") or ("REJECTED_AT_GATE1" if not r.get("gate1_pass") else "AWAITING_HOLDOUT")
        hyps.append({"id": name, "project": r.get("project"), "mechanism": r.get("mechanism"), "oos": r.get("oos"),
                     "oos_stress_2x": r.get("oos_stress_2x"), "direction_control": r.get("direction_control"),
                     "benchmark": r.get("benchmark"), "share_configs_positive": r.get("share_configs_positive"),
                     "gate1_checks": r.get("gate1_checks"), "gate1_pass": r.get("gate1_pass"),
                     "final_params": r.get("final_params"), "holdout": h, "verdict": verdict})
    conf = _load(V3_STATE / "confirm_a7.json") or _load(DOCS / "tradeden-v3.1-confirm_a7-2026-11-23.json")
    if conf:
        hyps.append({"id": conf["id"], "project": "A", "mechanism": "V3.1 confirmatory (post-hoc from development diagnostics, "
                     "one shot on the sealed holdout): trade gold against the dollar's FOMC-day move for one day.",
                     "oos": conf.get("development_in_sample_not_counted"), "oos_is_in_sample": True, "gate1_pass": True,
                     "holdout": {"holdout": conf.get("holdout"), "halves": conf.get("halves"), "checks": conf.get("checks"),
                                 "holm_p": (conf.get("holdout") or {}).get("p_one_sided")},
                     "direction_control": conf.get("direction_control"), "benchmark": {"mean_r": conf.get("always_long_mean_r"), "kind": "always_long_same_timing"},
                     "gate1_checks": {}, "verdict": conf.get("verdict"), "confirmatory": True})
    promoted = [h["id"] for h in hyps if h["verdict"] == "PROMOTED_TO_SHADOW"]
    return {"id": "tradeden-v3", "date": "2026-11-23", "scope": "macro releases, COT positioning, regimes; H1-weekly",
            "protocol_sha256": dev.get("protocol_sha256"), "generated": dev.get("generated"),
            "trials": _count_lines(V3_STATE / "ledger.jsonl", ("trial",)) or None,
            "hypotheses": hyps, "diagnostics": res.get("diagnostics"), "holdout_run": bool(hold) or bool(conf),
            "promoted": promoted, "verdict": ("EDGE_PROMOTED_TO_SHADOW" if promoted else ("NO_EDGE" if dev else "NOT_RUN")),
            "report": "docs/TRADEDEN_V3_REPORT.md"}


def overview() -> dict:
    programs = [edge_v1(), scalper_v1(), edge_v2(), v3()]
    trials = sum(p.get("trials") or 0 for p in programs) + 227   # +227 configs from programs before edge-discovery-v1
    return {"programs": programs, "cumulative_trials_on_gold_or_including_gold": trials,
            "cbot": cbot_lock(), "overall_verdict": "NO_EDGE" if not programs[-1]["promoted"] else "CANDIDATE_IN_SHADOW"}


@router.get("/api/research/overview")
def api_overview(request: Request):
    if os.getenv("TRADING_HUB_AUTH_MODE", "private") != "private" or not request.client or \
            request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "Local owner view only")
    return overview()
