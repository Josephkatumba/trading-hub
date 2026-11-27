"""cTrader desktop data feed (read-only).

The TradeDen Collector cBot (ctrader_scalper/cbot/TradeDenCollector.cs, data only, no order code) writes:

    Documents\\TradeDenScalper\\collector\\status.json                    snapshot, rewritten every few seconds
    Documents\\TradeDenScalper\\collector\\account-YYYYMMDD.jsonl        balance/equity every 60 s
    Documents\\TradeDenScalper\\collector\\deals.jsonl                   closed deals from cTrader history
    Documents\\TradeDenScalper\\collector\\bars\\<SYMBOL>\\M1-YYYYMMDD.jsonl closed M1 bars

(override the folder with CTRADER_COLLECTOR_DIR). This module only READS those files. It never talks to
cTrader and cannot place, modify or close orders. Nothing is estimated: when the collector has not written
recently, the feed is reported as disconnected and its last values are labelled with their age.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The collector rewrites status.json every `status_interval_seconds` (default 5 s).
# It counts as connected while the newest snapshot is younger than this.
CONNECTED_MAX_AGE_SECONDS = 30
# A quote whose last tick is older than this is shown as stale (market closed or symbol not ticking).
QUOTE_STALE_SECONDS = 120


def collector_dir() -> Path | None:
    env = os.getenv("CTRADER_COLLECTOR_DIR")
    candidates = [Path(env)] if env else []
    home = Path.home()
    candidates += [home / "OneDrive" / "Documents" / "TradeDenScalper" / "collector",
                   home / "Documents" / "TradeDenScalper" / "collector"]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _age(t: datetime | None, now: datetime) -> float | None:
    return None if t is None else round((now - t).total_seconds(), 1)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue      # e.g. a line being written right now
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return []
    return out


def _read_status(folder: Path) -> dict[str, Any] | None:
    try:
        rec = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return rec if isinstance(rec, dict) else None


def status(folder: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    folder = collector_dir() if folder is None else folder
    now = now or datetime.now(timezone.utc)
    base: dict[str, Any] = {
        "source": "ctrader_desktop", "read_only": True, "connected": False,
        "connected_max_age_seconds": CONNECTED_MAX_AGE_SECONDS, "collector_dir": str(folder) if folder else None,
        "last_update": None, "age_seconds": None, "collector": None, "account": None, "quotes": [], "positions": [],
        "missing_symbols": [], "deals_count": 0,
    }
    if folder is None:
        return {**base, "state": "not_installed",
                "reason": "collector folder not found; start the TradeDenCollector cBot in cTrader"}
    snap = _read_status(folder)
    if snap is None:
        return {**base, "state": "never_started", "reason": "no status.json written yet"}
    written = _ts(snap.get("written_at"))
    age = _age(written, now)
    cstate = snap.get("state")
    if cstate == "refused_live":
        state, reason = "refused_live", "collector refused to run on a LIVE account"
    elif cstate == "stopped":
        state, reason = "stopped", "collector cBot was stopped in cTrader"
    elif age is None:
        state, reason = "invalid", "status.json has no valid timestamp"
    elif age > CONNECTED_MAX_AGE_SECONDS:
        state, reason = "stale", f"no update for {int(age)} s (cTrader closed, cBot stopped or PC asleep)"
    else:
        state, reason = "connected", None
    quotes = []
    for q in snap.get("quotes") or []:
        tick_age = _age(_ts(q.get("last_tick_utc")), now)
        quotes.append({**q, "tick_age_seconds": tick_age,
                       "quote_fresh": state == "connected" and tick_age is not None and tick_age <= QUOTE_STALE_SECONDS})
    return {
        **base,
        "state": state, "reason": reason, "connected": state == "connected",
        "last_update": snap.get("written_at"), "age_seconds": age,
        "collector": {k: snap.get(k) for k in ("v", "run_id", "running_mode", "status_interval_seconds", "server_time",
                                                "write_errors")},
        "account": {k: snap.get(k) for k in ("account", "broker", "is_live", "currency", "leverage", "balance", "equity",
                                              "margin", "free_margin", "unrealized_net")},
        "quotes": quotes,
        "positions": snap.get("positions") or [],
        "missing_symbols": [s for s in str(snap.get("missing_symbols") or "").split(",") if s],
        "deals_count": len(deals(folder)),
    }


def bars(symbol: str, limit: int = 500, folder: Path | None = None) -> list[dict[str, Any]]:
    folder = collector_dir() if folder is None else folder
    if folder is None:
        return []
    sym_dir = folder / "bars" / symbol.upper()
    if not sym_dir.is_dir():
        return []
    by_t: dict[str, dict[str, Any]] = {}
    for f in sorted(sym_dir.glob("M1-*.jsonl"), reverse=True):      # newest day first
        for b in _jsonl(f):
            if isinstance(b.get("t"), str) and all(isinstance(b.get(k), (int, float)) for k in "ohlc"):
                by_t[b["t"]] = b                                        # restarts re-write backfill: dedupe on time
        if len(by_t) >= limit:
            break
    return [by_t[t] for t in sorted(by_t)][-limit:]


def deals(folder: Path | None = None) -> list[dict[str, Any]]:
    folder = collector_dir() if folder is None else folder
    if folder is None:
        return []
    seen: dict[Any, dict[str, Any]] = {}
    for d in _jsonl(folder / "deals.jsonl"):
        key = d.get("closing_deal_id") or (d.get("position_id"), d.get("close_time"))
        seen[key] = d
    return sorted(seen.values(), key=lambda d: str(d.get("close_time") or ""))


def equity(limit: int = 1440, folder: Path | None = None) -> list[dict[str, Any]]:
    folder = collector_dir() if folder is None else folder
    if folder is None:
        return []
    rows: list[dict[str, Any]] = []
    for f in sorted(folder.glob("account-*.jsonl"), reverse=True):
        day = [{k: r.get(k) for k in ("ts", "balance", "equity", "margin", "free_margin", "unrealized_net", "open_positions")}
               for r in _jsonl(f) if r.get("event") == "account"]
        rows = day + rows
        if len(rows) >= limit:
            break
    return rows[-limit:]
