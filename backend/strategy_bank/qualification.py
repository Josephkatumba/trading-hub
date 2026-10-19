"""Strategy qualification registry: the lifecycle of every strategy, with no limit on their number.

Append-only, timestamped status transitions (data/strategy_bank/qualification.jsonl); the latest
transition per key is the current status. Covers bank strategies (key = spec key) and research
library entries (key = "research:<library key>", imported from data/research/registry.json with
their original timestamps).

Statuses and what they allow:
  DISCOVERED        catalogued idea, not implemented
  RESEARCHING       being implemented / backtested
  BACKTESTED        passed historical validation; not yet scanned live
  FORWARD_TESTING   scanned live in SHADOW (RESEARCH spec): signals recorded and measured, never alerted
  QUALIFIED         promoted on recorded forward evidence + CEO approval: may alert
  APPROVED_EXPERIMENTAL  the T-034 bank strategies (CEO-approved experimental alerts)
  PRODUCTION        the original production strategies (bank #1-3 link to them)
  UNSUPPORTED       required data unavailable
  ARCHIVED          rejected or retired; results kept
Signals may be PUBLIC only in QUALIFIED, APPROVED_EXPERIMENTAL and PRODUCTION.

Promotion to QUALIFIED is gated in code on the strategy's RECORDED forward statistics (never on
backtests): >= MIN_FORWARD_SIGNALS resolved signals, expectancy >= MIN_EXPECTANCY_R, profit factor
>= MIN_PROFIT_FACTOR, plus a non-empty CEO approval reference.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage_config import data_directory

DISCOVERED, RESEARCHING, BACKTESTED = "DISCOVERED", "RESEARCHING", "BACKTESTED"
FORWARD_TESTING, QUALIFIED = "FORWARD_TESTING", "QUALIFIED"
APPROVED_EXPERIMENTAL, PRODUCTION = "APPROVED_EXPERIMENTAL", "PRODUCTION"
UNSUPPORTED, ARCHIVED = "UNSUPPORTED", "ARCHIVED"
STATUSES = (DISCOVERED, RESEARCHING, BACKTESTED, FORWARD_TESTING, QUALIFIED, APPROVED_EXPERIMENTAL, PRODUCTION,
            UNSUPPORTED, ARCHIVED)
RANK = {DISCOVERED: 0, RESEARCHING: 1, BACKTESTED: 2, FORWARD_TESTING: 3, APPROVED_EXPERIMENTAL: 4, QUALIFIED: 5, PRODUCTION: 6}
SIGNALLING = (QUALIFIED, APPROVED_EXPERIMENTAL, PRODUCTION)
EVALUATING = (RESEARCHING, BACKTESTED, FORWARD_TESTING)
REJECTED = (ARCHIVED, UNSUPPORTED)
MIN_FORWARD_SIGNALS, MIN_EXPECTANCY_R, MIN_PROFIT_FACTOR = 60, 0.05, 1.10
T034_COMMITTED_AT = "2026-10-19T10:31:02+00:00"        # commit b793cd1 (T-034 bank)
RESEARCH_STATUS_MAP = {"DISCOVERED": DISCOVERED, "RESEARCHING": RESEARCHING, "BACKTESTED": BACKTESTED,
                       "VALIDATED": BACKTESTED, "FORWARD_TESTING": FORWARD_TESTING,
                       "PRODUCTION_CANDIDATE": FORWARD_TESTING, "ARCHIVED": ARCHIVED}

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"path": None, "mtime": None, "rows": []}


def path() -> Path:
    return data_directory() / "strategy_bank" / "qualification.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> list[dict[str, Any]]:
    p = path()
    with _LOCK:
        mtime = p.stat().st_mtime_ns if p.exists() else None
        if _CACHE["path"] == str(p) and _CACHE["mtime"] == mtime:
            return _CACHE["rows"]
        rows = []
        if p.exists():
            with p.open("rb") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(row, dict) and row.get("key") and row.get("to") in STATUSES:
                        rows.append(row)
        _CACHE.update(path=str(p), mtime=mtime, rows=rows)
        return rows


def _append(row: dict[str, Any]) -> dict[str, Any]:
    p = path()
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("ab") as handle:
            handle.write((json.dumps(row, separators=(",", ":"), default=str) + "\n").encode("utf-8"))
        _CACHE["mtime"] = None
    return row


def history(key: str | None = None) -> list[dict[str, Any]]:
    return [r for r in _read() if key is None or r["key"] == key]


def current(key: str) -> dict[str, Any] | None:
    rows = history(key)
    return rows[-1] if rows else None


def current_status(key: str) -> str | None:
    row = current(key)
    return row["to"] if row else None


def transition(key: str, to: str, reason: str, *, name: str | None = None, source: str = "bank",
               at: str | None = None, evidence: dict[str, Any] | None = None, approval: str | None = None) -> dict[str, Any] | None:
    """Record a status change; a repeat of the current status is not re-recorded."""
    if to not in STATUSES:
        raise ValueError(f"unknown status {to!r}")
    before = current(key)
    if before and before["to"] == to:
        return None
    return _append({"key": key, "name": name or (before or {}).get("name") or key, "source": source,
                    "from": before["to"] if before else None, "to": to, "at": at or _now(), "reason": reason,
                    "evidence": evidence, "approval": approval})


# ----- seeding -------------------------------------------------------------------------------------------

def sync() -> int:
    """Baseline the bank specs (dated to the T-034 commit) and import research-registry history.
    Idempotent: only missing keys / transitions are written. Returns the number of rows added."""
    from strategy_bank import rules
    added = 0
    for spec in rules.SPECS:
        if current(spec["key"]):
            continue
        status = {rules.LINKED: PRODUCTION, rules.EXPERIMENTAL: APPROVED_EXPERIMENTAL,
                  rules.UNSUPPORTED: UNSUPPORTED}.get(spec["status"])
        if status:
            transition(spec["key"], status, "T-034 strategy bank baseline (CEO-approved bank)", name=spec["name"],
                       at=T034_COMMITTED_AT)
            added += 1
    reg_path = data_directory() / "research" / "registry.json"
    if reg_path.exists():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            reg = {}
        try:
            from research.library import LIBRARY
            names = {e["key"]: e["name"] for e in LIBRARY}
        except ImportError:                      # research package absent: keep the key as the name
            names = {}
        library_name = lambda k: names.get(k, k)
        for lib_key, entry in (reg.get("strategies") or {}).items():
            key = "research:" + lib_key
            known = {(r["to"], r["at"]) for r in history(key)}
            for h in entry.get("history", []):
                to = RESEARCH_STATUS_MAP.get(h.get("status"))
                if not to or (to, h.get("at")) in known:
                    continue
                row = transition(key, to, h.get("note") or "research registry", name=library_name(lib_key), source="research",
                                 at=h.get("at"))
                known.add((to, h.get("at")))
                added += row is not None
    return added


# ----- promotion gate ----------------------------------------------------------------------------------

def forward_evidence(key: str) -> dict[str, Any]:
    """The strategy's RECORDED forward statistics (bank store), never backtests."""
    from strategy_bank import engine
    store = engine.BankStore()
    rows = [s for s in store.signals.values() if s.get("strategy_key") == key]
    resolved = [float(s.get("r_multiple") or 0) for s in rows if s.get("outcome_status") in ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")]
    gains, losses = sum(r for r in resolved if r > 0), -sum(r for r in resolved if r < 0)
    return {"signals": len(rows), "resolved": len(resolved),
            "expectancy_r": round(sum(resolved) / len(resolved), 4) if resolved else None,
            "profit_factor": round(gains / losses, 3) if losses else None, "measured_at": _now()}


def promote(key: str, to: str, *, approval: str, evidence: dict[str, Any] | None = None, reason: str = "") -> dict[str, Any]:
    """Move a strategy up the lifecycle. QUALIFIED (alerting) needs FORWARD_TESTING first, the forward
    criteria met by recorded signals, and a CEO approval reference."""
    status = current_status(key)
    allowed = {RESEARCHING: (DISCOVERED, None), BACKTESTED: (RESEARCHING,), FORWARD_TESTING: (BACKTESTED,),
               QUALIFIED: (FORWARD_TESTING,)}
    if to not in allowed:
        raise ValueError(f"promote() cannot move to {to}")
    if status not in allowed[to]:
        raise ValueError(f"{key} is {status}; {to} requires {allowed[to]}")
    if to == QUALIFIED:
        if not approval or not approval.strip():
            raise ValueError("QUALIFIED requires a CEO approval reference")
        evidence = forward_evidence(key)
        e, pf = evidence["expectancy_r"], evidence["profit_factor"]
        if evidence["resolved"] < MIN_FORWARD_SIGNALS or e is None or e < MIN_EXPECTANCY_R or pf is None or pf < MIN_PROFIT_FACTOR:
            raise ValueError(f"forward evidence insufficient for {key}: {evidence} (needs >= {MIN_FORWARD_SIGNALS} resolved, "
                             f"expectancy >= {MIN_EXPECTANCY_R}R, PF >= {MIN_PROFIT_FACTOR})")
    return transition(key, to, reason or f"promoted to {to}", evidence=evidence, approval=approval or None)


def demote(key: str, to: str, reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Move a strategy down (e.g. QUALIFIED -> FORWARD_TESTING) or archive it; always recorded."""
    if to not in (FORWARD_TESTING, BACKTESTED, ARCHIVED):
        raise ValueError(f"demote() cannot move to {to}")
    if not reason.strip():
        raise ValueError("a demotion needs a reason")
    return transition(key, to, reason, evidence=evidence)


# ----- reporting (machine-readable, for the daily / weekly reports) --------------------------------------------

def _parse(value: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def lifecycle_report(start: datetime, end: datetime) -> dict[str, Any]:
    """Strategy lifecycle changes in [start, end) and the current counts.

    Returns:
      {"window": {"start": iso, "end": iso},
       "registered": [event], "promoted": [event], "demoted": [event], "rejected": [event],
       "transitions": [event],                      # every transition in the window, oldest first
       "counts": {"registered": int,                # every strategy known to the registry
                  "actively_evaluated": int,        # RESEARCHING / BACKTESTED / FORWARD_TESTING (no signal rights)
                  "qualified_to_signal": int,       # QUALIFIED / APPROVED_EXPERIMENTAL / PRODUCTION
                  "rejected_archived": int,         # ARCHIVED / UNSUPPORTED
                  "discovered": int,                # catalogued, not yet implemented
                  "by_status": {status: int}},
       "definitions": {...}}
    event = {"key", "name", "source" ("bank" | "research"), "from", "to", "at" (ISO UTC), "reason", "approval"}
    "registered" = first appearance of a key, or a move into DISCOVERED / RESEARCHING; "promoted" / "demoted"
    = moves up / down the lifecycle rank; "rejected" = moves into ARCHIVED or UNSUPPORTED."""
    rows = sorted(_read(), key=lambda r: str(r["at"]))
    first_seen: dict[str, str] = {}
    for r in rows:
        first_seen.setdefault(r["key"], r["at"])
    events = {"registered": [], "promoted": [], "demoted": [], "rejected": [], "transitions": []}
    for r in rows:
        t = _parse(r["at"])
        if t is None or not (start <= t < end):
            continue
        e = {k: r.get(k) for k in ("key", "name", "source", "from", "to", "at", "reason", "approval")}
        events["transitions"].append(e)
        if r["at"] == first_seen[r["key"]] or r["to"] in (DISCOVERED, RESEARCHING):
            events["registered"].append(e)
        if r["to"] in REJECTED:
            events["rejected"].append(e)
        elif r.get("from") in RANK and r["to"] in RANK:
            (events["promoted"] if RANK[r["to"]] > RANK[r["from"]] else events["demoted"]).append(e)
    latest: dict[str, str] = {}
    for r in rows:
        if (_parse(r["at"]) or end) < end:
            latest[r["key"]] = r["to"]
    by_status = {s: sum(v == s for v in latest.values()) for s in STATUSES}
    counts = {"registered": len(latest), "actively_evaluated": sum(by_status[s] for s in EVALUATING),
              "qualified_to_signal": sum(by_status[s] for s in SIGNALLING),
              "rejected_archived": sum(by_status[s] for s in REJECTED), "discovered": by_status[DISCOVERED],
              "by_status": by_status}
    return {"window": {"start": start.isoformat(), "end": end.isoformat()}, **events, "counts": counts,
            "definitions": {"actively_evaluated": list(EVALUATING), "qualified_to_signal": list(SIGNALLING),
                            "rejected_archived": list(REJECTED),
                            "note": "Counts are as of the window end. Research-library strategies use the key prefix 'research:'."}}
