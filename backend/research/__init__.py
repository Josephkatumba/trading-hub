"""TRADEden strategy research laboratory (T-032 onward).

Isolated from production: nothing here is registered in strategies.REGISTRY, read by
the scanner, written to the engine's stores or sent to Telegram. It replays the
production strategy classes (and experimental variants) bar by bar over cached MT5
history, simulates every signal with costs, and reports out-of-sample statistics.

  history.py      MT5 bar download + local cache (data dir/research/bars), UTC normalisation
  replay.py       no-look-ahead MarketInput reconstruction at each M15 bar open
  simulate.py     first-barrier trade simulation (spread, commission, slippage, M1 tie-break)
  metrics.py      expectancy, profit factor, drawdown, bootstrap confidence intervals
  experiments.py  experimental strategy variants, each with its trading rationale
  lab.py          signal generation, walk-forward evaluation and the experiment ledger (CLI)

`registry_events(start, end)` (below) is the read-only interface the daily / weekly reports use.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

_FINDING_KINDS = ("v6-test", "t033-test", "t036-bank-expansion", "baseline", "overlay", "composite", "new_strategy")


def _parse(value: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _e(stats: Any) -> float | None:
    return stats.get("expectancy_r") if isinstance(stats, dict) else None


def _finding(row: dict[str, Any]) -> str | None:
    """One plain-language sentence for a ledger entry (a simulated backtest result)."""
    name = row.get("name") or row.get("config") or "a strategy"
    for prefix in ("T036 ", "T033 FINALIST ", "V6 FINALIST ", "V6 R3 FINALIST ", "V6 "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    verdict = str(row.get("verdict") or "").split(" (")[0].lower()
    if row.get("kind") == "baseline":
        e = _e(row.get("development"))
        if e is None:
            return None
        sid = row.get("strategy_id") or name.replace("BASELINE ", "")
        return (f"Production strategy {sid}: {e:+.2f}R per trade in development replay after costs "
                f"({'negative' if e < 0 else 'positive but unproven'}).")
    if row.get("kind") == "t036-bank-expansion":
        if verdict == "not chosen":
            return None
        train, valid, test = _e(row.get("train")), _e(row.get("validation")), _e(row.get("test"))
        parts = [f"{label} {value:+.2f}R per trade" for label, value in (("training", train), ("validation", valid), ("test", test))
                 if value is not None]
        return f"{name}: {', '.join(parts) or 'no qualifying trades'}; {verdict or 'recorded'}."
    test = row.get("test") if isinstance(row.get("test"), dict) else None
    e = _e(test) if test else _e(row.get("development"))
    if e is None:
        return None
    where = "on the untouched test period" if test else "in development"
    return f"{name}: {e:+.2f}R per trade {where}; {verdict or 'recorded'}."


def registry_events(start: datetime, end: datetime) -> dict[str, Any]:
    """Strategy registry activity in [start, end) for the daily / weekly reports.

    Returns {"new": [{"name", "at"}], "testing": [name], "promoted": [{"name", "at", "to"}],
             "demoted": [{"name", "at", "to"}], "rejected": [{"name", "at"}],
             "counts": {"registered", "actively evaluated", "qualified to signal", "rejected/archived"},
             "discoveries": [str]}   # plain-language findings of SIMULATED backtests recorded in the window
    Reads only data/strategy_bank/qualification.jsonl and data/research/ledger.jsonl; no MT5, no
    backtests, no writes. An empty window (or missing files) gives empty lists and current counts."""
    from strategy_bank import qualification as q
    from storage_config import data_directory
    report = q.lifecycle_report(start, end)
    latest: dict[str, dict[str, Any]] = {}
    for row in sorted(q.history(), key=lambda r: str(r["at"])):
        t = _parse(row["at"])
        if t is not None and t < end:
            latest[row["key"]] = row
    testing = sorted(r.get("name") or k for k, r in latest.items() if r["to"] in q.EVALUATING)
    counts = report["counts"]
    discoveries: list[str] = []
    ledger = data_directory() / "research" / "ledger.jsonl"
    if ledger.exists():
        with ledger.open("rb") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                t = _parse(row.get("recorded_at"))
                if t is None or not (start <= t < end) or row.get("kind") not in _FINDING_KINDS:
                    continue
                text = _finding(row)
                if text and text not in discoveries:
                    discoveries.append(text)
    name = lambda e: e.get("name") or e["key"]
    return {"new": [{"name": name(e), "at": e["at"]} for e in report["registered"]
                    if e["to"] in (q.DISCOVERED, q.RESEARCHING)],
            "testing": testing,
            "promoted": [{"name": name(e), "at": e["at"], "to": e["to"]} for e in report["promoted"]],
            "demoted": [{"name": name(e), "at": e["at"], "to": e["to"]} for e in report["demoted"]],
            "rejected": [{"name": name(e), "at": e["at"]} for e in report["rejected"]],
            "counts": {"registered": counts["registered"], "actively evaluated": counts["actively_evaluated"],
                       "qualified to signal": counts["qualified_to_signal"], "rejected/archived": counts["rejected_archived"]},
            "discoveries": discoveries[:12]}
