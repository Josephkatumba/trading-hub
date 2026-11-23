"""TradeDen Scalper (cTrader cBot) journal reader and API.

The cBot appends JSON lines to Documents\\TradeDenScalper\\journal\\journal-YYYYMMDD.jsonl
(override with SCALPER_JOURNAL_DIR). This module only READS those files: it
never talks to cTrader and cannot place, modify or close orders.

Every number shown comes from a journal record written by the cBot from
cTrader's own position/history objects; nothing is estimated or filled in.
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

REPO = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO / "ctrader_scalper" / "reports"
HEARTBEAT_STALE_SECONDS = 180

router = APIRouter()


def journal_dir() -> Path | None:
    env = os.getenv("SCALPER_JOURNAL_DIR")
    candidates = [Path(env)] if env else []
    home = Path.home()
    candidates += [home / "OneDrive" / "Documents" / "TradeDenScalper" / "journal",
                   home / "Documents" / "TradeDenScalper" / "journal"]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_events(folder: Path | None = None) -> list[dict[str, Any]]:
    folder = folder if folder is not None else journal_dir()
    if folder is None:
        return []
    events = []
    for f in sorted(folder.glob("journal-*.jsonl")):
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("running_mode") not in (None, "RealTime"):
                    continue
                rec["_t"] = _ts(rec.get("ts"))
                if rec["_t"] is not None:
                    events.append(rec)
    events.sort(key=lambda r: r["_t"])
    return events


def closed_trades(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[Any, dict[str, Any]] = {}
    for e in events:
        if e.get("event") == "close" and e.get("net") is not None:
            seen[(e.get("run_id"), e.get("position_id"))] = e
    return sorted(seen.values(), key=lambda r: r["_t"])


def stats(trades: list[dict[str, Any]], start_balance: float | None = None) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "net_pnl": 0.0, "win_rate": None, "profit_factor": None, "avg_win": None,
                "avg_loss": None, "expectancy_r": None, "max_drawdown_pct": None, "trades_per_day": None,
                "commission": 0.0}
    net = [float(t["net"]) for t in trades]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]
    rs = [float(t["r_multiple"]) for t in trades if isinstance(t.get("r_multiple"), (int, float))]
    # drawdown on the realised balance path reported by cTrader
    balances = [float(t["balance_after"]) for t in trades if isinstance(t.get("balance_after"), (int, float))]
    dd = None
    if balances:
        first = start_balance if start_balance else balances[0] - net[0]
        peak, worst = first, 0.0
        for b in balances:
            peak = max(peak, b)
            worst = max(worst, (peak - b) / peak if peak else 0)
        dd = round(worst * 100, 2)
    days = {t["_t"].date() for t in trades}
    return {
        "trades": len(net),
        "net_pnl": round(sum(net), 2),
        "win_rate": round(len(wins) / len(net) * 100, 1),
        "profit_factor": round(sum(wins) / -sum(losses), 3) if sum(losses) < 0 else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
        "max_drawdown_pct": dd,
        "trades_per_day": round(len(net) / max(len(days), 1), 2),
        "commission": round(sum(float(t.get("commission") or 0) for t in trades), 2),
    }


def _group(trades, key):
    groups = defaultdict(list)
    for t in trades:
        groups[str(t.get(key) or "unknown")].append(t)
    return {k: stats(v) for k, v in sorted(groups.items())}


def latest_backtest() -> dict[str, Any] | None:
    files = sorted(REPORTS_DIR.glob("walkforward_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    try:
        rep = json.loads(files[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "file": files[-1].name,
        "generated_utc": rep.get("generated_utc"),
        "strategy_version": rep.get("strategy_version"),
        "walk_forward": rep.get("walk_forward"),
        "symbols": [{"symbol": s["symbol"], "verdict": s.get("verdict"), "out_of_sample": s.get("out_of_sample"),
                     "configs_tested": s.get("configs_tested"),
                     "configs_profitable_in_sample": s.get("configs_profitable_in_sample"),
                     "data": s.get("data")} for s in rep.get("symbols", [])],
        "portfolio_oos": rep.get("portfolio_oos"),
    }


def _public(e: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def summary(events: list[dict[str, Any]] | None = None, now: datetime | None = None) -> dict[str, Any]:
    events = read_events() if events is None else events
    now = now or datetime.now(timezone.utc)
    starts = [e for e in events if e.get("event") == "start"]
    start = starts[-1] if starts else None
    hb = next((e for e in reversed(events) if e.get("event") == "heartbeat"), None)
    trades = closed_trades(events)
    first_balance = None
    if starts:
        first_balance = float(starts[0].get("balance") or 0) or None
    today = now.date()
    today_trades = [t for t in trades if t["_t"].date() == today]
    daily = defaultdict(lambda: {"net": 0.0, "trades": 0})
    for t in trades:
        d = daily[t["_t"].date().isoformat()]
        d["net"] = round(d["net"] + float(t["net"]), 2)
        d["trades"] += 1
    signals = [e for e in events if e.get("event") == "signal"]
    decisions = Counter(e.get("decision") for e in signals)
    skip_reasons = Counter(_reason_bucket(e.get("reason")) for e in signals if e.get("decision") == "skipped")
    hb_age = (now - hb["_t"]).total_seconds() if hb else None
    stopped = bool(events) and events[-1].get("event") == "stop"
    status = "never_started" if not events else ("stopped" if stopped else (
        "running" if hb_age is not None and hb_age <= HEARTBEAT_STALE_SECONDS else "offline"))
    feed = [_public(e) for e in events if e.get("event") in ("start", "stop", "safety", "halt", "close", "time_exit", "breakeven")
            or (e.get("event") == "signal" and e.get("decision") in ("opened", "order_failed"))][-60:]
    equity_curve = [{"t": t["_t"].isoformat(), "balance": t.get("balance_after")} for t in trades if t.get("balance_after") is not None]
    return {
        "journal_dir": str(journal_dir()) if journal_dir() else None,
        "bot_status": status,
        "heartbeat_age_seconds": round(hb_age) if hb_age is not None else None,
        "account": None if start is None else {k: start.get(k) for k in (
            "demo_verified", "verification", "is_live", "account", "broker", "currency", "leverage", "account_type",
            "balance", "symbols", "execution_mode", "params", "ts", "v")},
        "live_account_ever_seen": any(e.get("is_live") is True for e in starts),
        "risk": None if hb is None else {k: hb.get(k) for k in (
            "balance", "equity", "day_start_balance", "realized_today", "open_risk", "daily_limit",
            "consecutive_losses", "halted", "halt_reason", "mode", "ts")},
        "open_positions": (hb or {}).get("positions") or [],
        "performance": stats(trades, first_balance),
        "today": stats(today_trades),
        "by_symbol": _group(trades, "symbol"),
        "by_setup": _group(trades, "setup"),
        "by_session": _group(trades, "session"),
        "daily_pnl": [{"date": k, **v} for k, v in sorted(daily.items())],
        "equity_curve": equity_curve,
        "signals": {"total": len(signals), "decisions": dict(decisions), "skip_reasons": dict(skip_reasons.most_common(12))},
        "feed": feed[::-1],
        "backtest": latest_backtest(),
    }


def _reason_bucket(reason: Any) -> str:
    r = str(reason or "unknown")
    for prefix in ("score ", "cost/risk", "stop distance"):
        if r.startswith(prefix):
            return prefix.strip()
    if r.endswith("consecutive losses today"):
        return "consecutive losses"
    return r


def daily_report(day: str, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = read_events() if events is None else events
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(400, "date must be YYYY-MM-DD") from exc
    day_events = [e for e in events if e["_t"].date() == d]
    trades = [t for t in closed_trades(events) if t["_t"].date() == d]
    s = stats(trades)
    signals = [e for e in day_events if e.get("event") == "signal"]
    skips = Counter(_reason_bucket(e.get("reason")) for e in signals if e.get("decision") == "skipped")
    halts = [_public(e) for e in day_events if e.get("event") in ("halt", "safety")]
    lines = [f"# TradeDen Scalper - end of day {day} (UTC)", "",
             "Source: cBot journal written from cTrader position history. Demo account.", "",
             f"- Closed trades: {s['trades']}", f"- Net P&L: {s['net_pnl']}",
             f"- Win rate: {s['win_rate']}%" if s["win_rate"] is not None else "- Win rate: n/a",
             f"- Profit factor: {s['profit_factor']}", f"- Expectancy (R): {s['expectancy_r']}",
             f"- Commission paid: {s['commission']}",
             f"- Signals seen: {len(signals)}; opened: {sum(1 for e in signals if e.get('decision') == 'opened')}", ""]
    if trades:
        lines += ["| Exit (UTC) | Symbol | Side | Setup | Score | Reason | Net | R |", "|---|---|---|---|---|---|---|---|"]
        for t in trades:
            r = t.get("r_multiple")
            lines.append(f"| {t['_t']:%H:%M} | {t.get('symbol')} | {t.get('side')} | {t.get('setup')} | {t.get('score')} | "
                         f"{t.get('reason')} | {t.get('net')} | {round(r, 2) if isinstance(r, (int, float)) else ''} |")
        lines.append("")
    if skips:
        lines += ["Skipped signals (missed opportunities) by reason:", *[f"- {k}: {v}" for k, v in skips.most_common()], ""]
    if halts:
        lines += ["Risk events:", *[f"- {h.get('ts')}: {h.get('event')} - {h.get('reason') or h.get('message')}" for h in halts], ""]
    if s["trades"] < 30:
        lines.append(f"Evidence note: {s['trades']} trades is far too few to judge an edge; treat this as a log, not a verdict.")
    return {"date": day, "stats": s, "trades": [_public(t) for t in trades], "skip_reasons": dict(skips),
            "risk_events": halts, "markdown": "\n".join(lines)}


def _local_only(request: Request) -> None:
    if os.getenv("TRADING_HUB_AUTH_MODE", "private") != "private" or not request.client or \
            request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "Local owner view only")


@router.get("/api/scalper/summary")
def api_summary(request: Request):
    _local_only(request)
    return summary()


@router.get("/api/scalper/trades")
def api_trades(request: Request, limit: int = Query(200, ge=1, le=5000)):
    _local_only(request)
    return {"trades": [_public(t) for t in closed_trades(read_events())][-limit:][::-1]}


@router.get("/api/scalper/daily-report")
def api_daily_report(request: Request, date: str | None = None):
    _local_only(request)
    return daily_report(date or datetime.now(timezone.utc).date().isoformat())
