"""TradeDen daily and weekly Telegram performance reports (CEO directive, Parts 2-4).

Schedule, Africa/Kampala (UTC+3), every report from RECORDED data only:
  daily    every day at 23:00. Window: the previous day 23:00 -> this day 23:00.
  weekly   every Friday at 23:00. Window: Saturday 00:00 -> Friday 23:00 (the stated cutoff;
           nothing after 23:00 is included). Friday 23:00-24:00 belongs to no weekly window; it
           is covered by Saturday's daily report.
  Fridays  the daily report is sent first, then the weekly report, as separate messages.

Reliability: every report is keyed by (kind, date) in reports/reports.jsonl, so a restart never
sends one twice; slots missed while TradeDen was offline are generated after it restarts and
marked DELAYED (at most MAX_CATCH_UP per kind). Nothing is sent for slots before activation.
Reports and weekly PDFs are kept in <data dir>/reports.

What the numbers are:
  PAPER SIGNALS       confirmed signals and their HYPOTHETICAL outcomes: the first level each
                      confirmed plan reached on MT5 candles (signal_outcomes.py for production
                      strategies, the bank's own resolver for bank strategies). R is planned R,
                      spread in the fills, no commission.
  BACKTESTS           only in the research section, always labelled simulated.
  EXECUTED TRADES     none: TradeDen executes no trades.

The report is computed inside the engine (its indexes are already in memory): the scheduler
thread, and the read-only preview route that the on-demand CLI uses.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from storage_config import data_directory

LOGGER = logging.getLogger("trading_hub.reports")
KAMPALA = ZoneInfo("Africa/Kampala")
LONDON, NEW_YORK = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
REPORT_AT = time(23, 0)
FRIDAY = 4
ENABLED_ENV = "TRADEDEN_TELEGRAM_REPORTS_ENABLED"
HEARTBEAT_SECONDS = 60
MAX_CATCH_UP = {"daily": 7, "weekly": 2}
KIND_ORDER = {"daily": 0, "weekly": 1}          # Fridays: daily first, then weekly
DECISIVE = ("TARGET_HIT", "STOP_HIT")
RESOLVED = ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")
FINAL = ("TARGET_HIT", "STOP_HIT", "TIME_EXIT", "AMBIGUOUS", "NO_HIT", "UNAVAILABLE")
SMALL_SAMPLE = 10
LIVE_PRODUCTION = ("trendline_v5", "support_resistance", "trend_momentum", "smc")
DELAY_AFTER = timedelta(minutes=15)
LABELS = ("Paper signals: hypothetical outcomes of confirmed signals on MT5 candles (planned R, spread included, "
          "no commission). Backtests: simulated, research section only. Executed trades: none - TradeDen executes no trades.")
OFFLINE_NOTE = "TradeDen cannot scan markets or send alerts while the laptop or engine is offline."


def reports_dir() -> Path:
    return data_directory() / "reports"


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "").strip() == "1"


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


# ----- schedule ---------------------------------------------------------------------------------------

def slot_for(day: date) -> datetime:
    return datetime.combine(day, REPORT_AT, KAMPALA)


def due_slots(kind: str, after: datetime, now: datetime) -> list[datetime]:
    """Report slots of `kind` in (after, now], oldest first."""
    slots = []
    day = after.astimezone(KAMPALA).date()
    last = now.astimezone(KAMPALA).date()
    while day <= last:
        if kind == "daily" or (kind == "weekly" and day.weekday() == FRIDAY):
            slot = slot_for(day)
            if after < slot <= now:
                slots.append(slot)
        day += timedelta(days=1)
    return slots


def window(kind: str, slot: datetime) -> tuple[datetime, datetime]:
    local = slot.astimezone(KAMPALA)
    if kind == "weekly":
        saturday = local.date() - timedelta(days=(local.weekday() - 5) % 7)
        return datetime.combine(saturday, time(0, 0), KAMPALA), local
    return local - timedelta(days=1), local


def latest_daily_window(now: datetime) -> tuple[datetime, datetime]:
    """For an on-demand report: since the last 23:00 slot, up to now."""
    local = now.astimezone(KAMPALA)
    today = slot_for(local.date())
    start = today if local >= today else today - timedelta(days=1)
    return start, local


# ----- unified strategy identity (as the dashboard: strategyUnified.mjs) ----------------------------------

PRODUCTION_NAMES = {"support_resistance": ("support_resistance", "Support & Resistance"),
                    "trend_momentum": ("prod:trend_momentum", "Trend / Momentum"),
                    "smc": ("prod:smc", "Smart Money Concepts")}


def unified(strategy_id: str, setup_type: Any = None) -> tuple[str, str]:
    if strategy_id == "trendline_v5":
        family = str(setup_type or "").upper()
        if family == "BREAK":
            return "trendline_break_retest", "Trendline Break & Retest"
        if family == "REVERSAL":
            return "trendline_bounce", "Trendline Bounce"
        return "prod:trendline_v5", "Trendline (context)"
    return PRODUCTION_NAMES.get(strategy_id, ("prod:" + strategy_id, strategy_id.replace("_", " ").title()))


def session_of(instant: datetime) -> str:
    london, ny = instant.astimezone(LONDON).time(), instant.astimezone(NEW_YORK).time()
    in_london, in_ny = time(8) <= london < time(16, 30), time(8) <= ny < time(17)
    return "London/NY overlap" if in_london and in_ny else "London" if in_london else "New York" if in_ny else "Asia/off-hours"


# ----- data sources -----------------------------------------------------------------------------------------

def heartbeat_file() -> Path:
    return data_directory() / "engine_heartbeat.jsonl"


def heartbeats() -> list[datetime]:
    path = heartbeat_file()
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stamp = _parse(line.strip().strip('"'))
            if stamp:
                out.append(stamp)
    return out


def uptime(start: datetime, end: datetime, beats: Iterable[datetime]) -> dict[str, Any]:
    """Share of [start, end) covered by heartbeats (a beat covers the following 2 minutes). Time
    before the first heartbeat ever recorded is UNMEASURED (heartbeat logging did not exist yet),
    not counted as downtime."""
    beats = sorted(beats)
    measured_from = max(start, min(beats[0], end)) if beats else end
    unmeasured = (measured_from - start).total_seconds()
    covered, cursor = 0.0, start
    for beat in (b for b in beats if start - timedelta(minutes=2) <= b < end):
        lo, hi = max(beat, cursor), min(end, beat + timedelta(seconds=2 * HEARTBEAT_SECONDS))
        if hi > lo:
            covered += (hi - lo).total_seconds()
            cursor = hi
    total = (end - start).total_seconds() - unmeasured
    return {"coverage": round(covered / total, 4) if total > 0 else None, "offline_hours": round(max(0.0, total - covered) / 3600, 1),
            "unmeasured_hours": round(unmeasured / 3600, 1)}


def _latest_by(path: Path, key: str) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if path.exists():
        with path.open("rb") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(row, dict) and row.get(key):
                    out[str(row[key])] = row
    return list(out.values())


class Sources:
    """Everything a report reads. Each attribute is a zero-argument callable; tests inject fakes."""

    def __init__(self, **overrides: Callable[[], Any]) -> None:
        self.confirmations = overrides.get("confirmations") or self._confirmations
        self.outcomes = overrides.get("outcomes") or self._outcomes
        self.bank_signals = overrides.get("bank_signals") or (lambda: _latest_by(data_directory() / "strategy_bank" / "signals.jsonl", "signal_id"))
        self.bank_opportunities = overrides.get("bank_opportunities") or (lambda: _latest_by(data_directory() / "strategy_bank" / "opportunities.jsonl", "opportunity_id"))
        self.first_seen = overrides.get("first_seen") or self._first_seen
        self.lifecycle = overrides.get("lifecycle") or self._lifecycle
        self.beats = overrides.get("beats") or heartbeats
        self.live_alerts = overrides.get("live_alerts") or (lambda: _latest_by(data_directory() / "telegram_notifications.jsonl", "key"))
        self.bank_alerts = overrides.get("bank_alerts") or (lambda: _latest_by(data_directory() / "strategy_bank" / "telegram_notifications.jsonl", "key"))
        self.health = overrides.get("health") or (lambda: {})
        self.research = overrides.get("research") or default_research
        self.live = overrides.get("live") or (lambda: set(LIVE_PRODUCTION))

    @staticmethod
    def _confirmations() -> list[dict[str, Any]]:
        from observations import confirmation_events
        return confirmation_events()

    @staticmethod
    def _outcomes() -> list[dict[str, Any]]:
        import signal_outcomes
        return signal_outcomes.OutcomeStore().all_latest()

    @staticmethod
    def _first_seen() -> dict[str, dict[str, Any]]:
        """setup_id -> its first recorded observation (time, strategy, shadow, setup type)."""
        from observations import _observation_index
        seen: dict[str, dict[str, Any]] = {}
        for row in _observation_index().summaries():
            sid = row.get("setup_id")
            if row.get("rt") != "setup_snapshot" or not sid or sid in seen:
                continue
            seen[sid] = {"at": row.get("observed_at"), "strategy_id": row.get("strategy_id") or "trendline",
                         "shadow": row.get("shadow") is True, "setup_type": row.get("setup_type"), "symbol": row.get("symbol")}
        return seen

    @staticmethod
    def _lifecycle() -> list[dict[str, Any]]:
        from observations import lifecycle_events
        return [row for row in lifecycle_events() if row.get("to_state") in ("INVALIDATED", "EXPIRED")]


def default_research(start: datetime, end: datetime) -> dict[str, Any] | None:
    """Strategy research events from the qualification registry, when available."""
    try:
        from research import registry_events          # provided by the research lab
    except ImportError:
        return None
    try:
        return registry_events(start, end)
    except Exception:
        LOGGER.exception("Research registry unavailable for the report")
        return None


# ----- signal rows ------------------------------------------------------------------------------------------

def signal_rows(sources: Sources) -> list[dict[str, Any]]:
    """Every confirmed PAPER signal of a live production strategy or the bank, with its outcome."""
    live = sources.live()
    outcomes = {row.get("setup_id"): row for row in sources.outcomes()}
    rows = []
    for c in sources.confirmations():
        sid = str(c.get("strategy_id") or "trendline")
        if c.get("shadow") is True or sid not in live:
            continue
        key, name = unified(sid, c.get("setup_type"))
        o = outcomes.get(c.get("setup_id")) or {}
        rr = None
        try:
            entry, stop, target = float(o["entry"]), float(o["stop_loss"]), float(o["take_profit"])
            rr = abs(target - entry) / abs(entry - stop) if entry != stop else None
        except (KeyError, TypeError, ValueError):
            pass
        rows.append({"source": "production", "id": c.get("setup_id"), "key": key, "name": name, "symbol": c.get("symbol"),
                     "direction": c.get("direction"), "confirmed_at": c.get("confirmed_at"), "rr": rr,
                     "status": o.get("status") or "PENDING", "hit_at": o.get("hit_at"), "r": o.get("r_multiple")})
    for s in sources.bank_signals():
        rows.append({"source": "bank", "id": s.get("signal_id"), "key": s.get("strategy_key"), "name": s.get("strategy_name"),
                     "symbol": s.get("symbol"), "direction": s.get("direction"), "confirmed_at": s.get("confirmed_at"),
                     "rr": s.get("rr"), "status": s.get("outcome_status") or "PENDING", "hit_at": s.get("outcome_at"),
                     "r": s.get("r_multiple"), "opportunity_id": s.get("opportunity_id"), "bank_status": s.get("status")})
    return rows


def _within(value: Any, start: datetime, end: datetime) -> bool:
    stamp = _parse(value)
    return stamp is not None and start <= stamp < end


def _r(row: dict[str, Any]) -> float:
    try:
        return float(row.get("r")) if row.get("status") in RESOLVED and row.get("r") is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(r["status"] == "TARGET_HIT" for r in rows)
    sl = sum(r["status"] == "STOP_HIT" for r in rows)
    te = sum(r["status"] == "TIME_EXIT" for r in rows)
    resolved = tp + sl + te
    net = round(sum(_r(r) for r in rows), 2)
    return {"tp": tp, "sl": sl, "time_exit": te, "net_r": net, "n": resolved,
            "win_rate": round(tp / (tp + sl), 3) if tp + sl else None,
            "expectancy": round(net / resolved, 3) if resolved else None}


def _group(rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return dict(sorted(((k, _stats(v)) for k, v in groups.items()), key=lambda kv: (-kv[1]["net_r"], kv[0])))


def _ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((r for r in rows if r["status"] in RESOLVED), key=lambda r: str(r.get("hit_at")))


def _drawdown(rows: list[dict[str, Any]]) -> float:
    peak = equity = worst = 0.0
    for row in _ordered(rows):
        equity += _r(row)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def _streaks(rows: list[dict[str, Any]]) -> dict[str, int]:
    best = {"wins": 0, "losses": 0}
    run_kind, run = None, 0
    for row in _ordered(rows):
        kind = "wins" if _r(row) > 0 else "losses"
        run = run + 1 if kind == run_kind else 1
        run_kind = kind
        best[kind] = max(best[kind], run)
    return best


def _delivery(sources: Sources, start: datetime, end: datetime, ledger: "ReportLedger | None") -> dict[str, Any]:
    def count(rows: list[dict[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for row in rows:
            stamp = row.get("sent_at") or row.get("updated_at")
            if _within(stamp, start, end) and row.get("status") in ("sent", "failed", "expired"):
                out[row["status"]] += 1
        return {"sent": out["sent"], "failed": out["failed"], "expired": out["expired"]}
    previous = None
    if ledger is not None:
        reports = [row for row in ledger.rows() if str(row.get("key", "")).split(":")[0] in ("daily", "weekly")]
        if reports:
            last = max(reports, key=lambda row: str(row.get("updated_at")))
            previous = {"key": last.get("key"), "status": last.get("status"), "delayed": bool(last.get("late"))}
    return {"live_alerts": count(sources.live_alerts()), "bank_alerts": count(sources.bank_alerts()), "previous_report": previous}


# ----- compute ------------------------------------------------------------------------------------------------

def compute_daily(start: datetime, end: datetime, sources: Sources, ledger: "ReportLedger | None" = None) -> dict[str, Any]:
    rows = signal_rows(sources)
    live = sources.live()
    seen = sources.first_seen()
    detected = [v for v in seen.values() if not v["shadow"] and v["strategy_id"] in live and _within(v["at"], start, end)]
    confirmed = [r for r in rows if _within(r["confirmed_at"], start, end)]
    realised = [r for r in rows if r["status"] in RESOLVED and _within(r["hit_at"], start, end)]
    active = [r for r in rows if r["status"] not in FINAL and (_parse(r["confirmed_at"]) or end) < end]
    closed_events = [e for e in sources.lifecycle() if _within(e.get("occurred_at"), start, end)
                     and (seen.get(e.get("setup_id")) or {}).get("strategy_id") in live and not (seen.get(e.get("setup_id")) or {}).get("shadow")]
    undecided = [r for r in rows if r["status"] in ("AMBIGUOUS", "NO_HIT", "UNAVAILABLE") and _within(r["hit_at"] or r["confirmed_at"], start, end)]
    stats = _stats(realised)
    by_strategy = _group(realised, lambda r: r["name"])
    ranked = [(name, s) for name, s in by_strategy.items() if s["n"]]
    research = sources.research(start, end)
    health = sources.health() or {}
    report = {
        "kind": "daily", "window": {"start": start.isoformat(), "end": end.isoformat()},
        "detected": len(detected), "detected_by_strategy": dict(sorted(_count(detected, lambda v: unified(v["strategy_id"], v["setup_type"])[1]).items())),
        "confirmed": len(confirmed), "confirmed_production": sum(r["source"] == "production" for r in confirmed),
        "confirmed_bank": sum(r["source"] == "bank" for r in confirmed),
        "confirmed_by_strategy": dict(sorted(_count(confirmed, lambda r: r["name"]).items(), key=lambda kv: -kv[1])),
        "take_profits": stats["tp"], "stop_losses": stats["sl"], "time_exits": stats["time_exit"],
        "win_rate": stats["win_rate"], "net_r": stats["net_r"], "expectancy": stats["expectancy"],
        "active": len(active), "unresolved": len(undecided),
        "invalidated": sum(e.get("to_state") == "INVALIDATED" for e in closed_events),
        "expired": sum(e.get("to_state") == "EXPIRED" for e in closed_events),
        "expired_unconfirmed": sum(e.get("to_state") == "EXPIRED" and e.get("from_state") not in ("CONFIRMED", "ACTIVE") for e in closed_events),
        "by_strategy": by_strategy, "by_instrument": _group(realised, lambda r: str(r["symbol"])),
        "best": ranked[0] if ranked else None, "worst": ranked[-1] if len(ranked) > 1 else None,
        "research": research, "uptime": uptime(start, end, sources.beats()), "health": health,
        "delivery": _delivery(sources, start, end, ledger),
    }
    report["observations"] = _observations(report, realised, rows, end)
    return report


def _count(items: Iterable[Any], key: Callable[[Any], str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for item in items:
        out[key(item)] += 1
    return dict(out)


def _observations(report: dict[str, Any], realised: list[dict[str, Any]], rows: list[dict[str, Any]], end: datetime) -> list[str]:
    notes = []
    offline = report["uptime"]["offline_hours"]
    if offline and offline >= 0.5:
        notes.append(f"Engine offline for about {offline} h in this window: nothing could be scanned or sent then.")
    for symbol, s in report["by_instrument"].items():
        if s["sl"] >= 3 and s["tp"] == 0:
            notes.append(f"{symbol}: {s['sl']} stops and no targets.")
    for name, s in report["by_strategy"].items():
        if s["sl"] >= 3 and s["tp"] == 0:
            notes.append(f"{name}: {s['sl']} stops and no targets in this window.")
    if report["confirmed_bank"] and report["confirmed_bank"] >= 3 * max(1, report["confirmed_production"]):
        notes.append("Most confirmations came from experimental bank strategies, none of which has demonstrated profitability.")
    month = [r for r in rows if r["status"] in RESOLVED and (_parse(r["hit_at"]) or end) >= end - timedelta(days=30)]
    s = _stats(month)
    if s["n"] >= SMALL_SAMPLE and s["expectancy"] is not None and s["expectancy"] < 0:
        notes.append(f"Last 30 days: {s['expectancy']:+.2f}R per resolved signal over {s['n']} signals. Signals are not yet profitable on paper.")
    if not report["confirmed"] and not offline:
        notes.append("No setup passed confirmation in this window; that is a valid outcome, not a fault.")
    return notes or ["Nothing unusual recorded."]


def compute_weekly(start: datetime, end: datetime, sources: Sources, ledger: "ReportLedger | None" = None) -> dict[str, Any]:
    rows = signal_rows(sources)
    confirmed = [r for r in rows if _within(r["confirmed_at"], start, end)]
    realised = [r for r in rows if r["status"] in RESOLVED and _within(r["hit_at"], start, end)]
    stats = _stats(realised)
    rr = [float(r["rr"]) for r in confirmed if isinstance(r.get("rr"), (int, float))]
    days = max(1.0, (end - start).total_seconds() / 86400)
    # Leaderboard: this week's resolved paper signals, every strategy with at least one.
    board = [{"name": name, **s, "small": s["n"] < SMALL_SAMPLE} for name, s in _group(realised, lambda r: r["name"]).items() if s["n"]]
    board.sort(key=lambda s: (-(s["expectancy"] or 0), -s["n"], s["name"]))
    prior_start = start - timedelta(days=28)
    prior = _group([r for r in rows if r["status"] in RESOLVED and _within(r["hit_at"], prior_start, start)], lambda r: r["name"])
    trend = {"improving": [], "declining": []}
    for item in board:
        before = prior.get(item["name"])
        if before and before["n"] >= 5 and item["n"] >= 5 and before["expectancy"] is not None:
            delta = item["expectancy"] - before["expectancy"]
            if abs(delta) >= 0.25:
                trend["improving" if delta > 0 else "declining"].append(
                    {"name": item["name"], "week": item["expectancy"], "prior": before["expectancy"], "n": item["n"], "prior_n": before["n"]})
    all_time = _group([r for r in rows if r["status"] in RESOLVED and (_parse(r["hit_at"]) or end) < end], lambda r: r["name"])
    names = sorted({r["name"] for r in rows if r.get("name")})
    needs_testing = [name for name in names if (all_time.get(name) or {}).get("n", 0) < SMALL_SAMPLE]
    opportunities = sources.bank_opportunities()
    multi = [o for o in opportunities if len(o.get("strategies") or []) > 1 and _within(o.get("first_confirmed_at"), start, end)]
    week_bank = [r for r in confirmed if r["source"] == "bank"]
    instruments = _count(confirmed, lambda r: str(r["symbol"]))
    top_share = (max(instruments.values()) / len(confirmed)) if confirmed else None
    previous_weeks = []
    for back in range(1, 5):
        ws, we = start - timedelta(days=7 * back), end - timedelta(days=7 * back)
        previous_weeks.append({"week_ending": we.date().isoformat(), **_stats([r for r in rows if r["status"] in RESOLVED and _within(r["hit_at"], ws, we)])})
    report = {
        "kind": "weekly", "window": {"start": start.isoformat(), "end": end.isoformat()},
        "confirmed": len(confirmed), "confirmed_production": sum(r["source"] == "production" for r in confirmed), "confirmed_bank": len(week_bank),
        "take_profits": stats["tp"], "stop_losses": stats["sl"], "time_exits": stats["time_exit"], "win_rate": stats["win_rate"],
        "net_r": stats["net_r"], "expectancy": stats["expectancy"], "avg_rr": round(sum(rr) / len(rr), 2) if rr else None,
        "by_instrument": _group(realised, lambda r: str(r["symbol"])),
        "by_session": _group(realised, lambda r: session_of(_parse(r["confirmed_at"]) or end)),
        "top": board[:10], "bottom": list(reversed(board[10:]))[:10] if len(board) > 10 else [],
        "improving": trend["improving"], "declining": trend["declining"], "needs_testing": needs_testing,
        "research": sources.research(start, end),
        "max_drawdown_r": _drawdown(realised), "streaks": _streaks(realised),
        "signals_per_day": round(len(confirmed) / days, 1),
        "frequency_by_strategy": dict(sorted(_count(confirmed, lambda r: r["name"]).items(), key=lambda kv: -kv[1])[:8]),
        "correlation": {"multi_strategy_opportunities": len(multi), "bank_signals": len(week_bank),
                        "top_instrument_share": round(top_share, 2) if top_share is not None else None,
                        "top_instrument": max(instruments, key=instruments.get) if instruments else None},
        "previous_weeks": previous_weeks, "uptime": uptime(start, end, sources.beats()), "health": sources.health() or {},
        "delivery": _delivery(sources, start, end, ledger),
    }
    report["priorities"] = _priorities(report, all_time)
    return report


def _priorities(report: dict[str, Any], all_time: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    markets, validate, improve = [], [], []
    for symbol, s in report["by_instrument"].items():
        if s["sl"] >= 3 and (s["win_rate"] or 0) < 0.25:
            markets.append(f"{symbol}: {s['tp']} TP / {s['sl']} SL this week. Investigate whether the conditions on this market suit the strategies firing on it.")
    for name, s in all_time.items():
        if s["n"] >= SMALL_SAMPLE and (s["expectancy"] or 0) < 0:
            validate.append(f"{name}: {s['expectancy']:+.2f}R per signal over {s['n']} resolved. Review in the research lab or demote.")
    if report["needs_testing"]:
        validate.append(f"{len(report['needs_testing'])} strategies have fewer than {SMALL_SAMPLE} resolved signals: no conclusion is possible yet.")
    corr = report["correlation"]
    if corr["multi_strategy_opportunities"]:
        improve.append(f"{corr['multi_strategy_opportunities']} opportunities were confirmed by several strategies at once: their results are correlated, not independent evidence.")
    if corr["top_instrument_share"] and corr["top_instrument_share"] >= 0.3:
        improve.append(f"{int(corr['top_instrument_share'] * 100)}% of the week's signals were on {corr['top_instrument']}: results are concentrated.")
    if (report["uptime"]["coverage"] or 1) < 0.9:
        improve.append("Keep the engine running through the week: downtime leaves gaps in scanning, alerts and outcome tracking.")
    return {"markets": markets or ["No market stood out this week."],
            "validation": validate or ["No strategy has enough resolved signals to call for review."],
            "improvements": improve or ["No structural concern this week."]}


# ----- rendering -------------------------------------------------------------------------------------------

def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _local(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(KAMPALA).strftime("%a %d %b %H:%M")


def _strategy_line(name: str, s: dict[str, Any]) -> str:
    return (f"  {name}: {s['tp']} TP / {s['sl']} SL" + (f" / {s['time_exit']} time exits" if s.get("time_exit") else "")
            + f", {s['net_r']:+.2f}R" + (f" (n={s['n']}, small sample)" if s["n"] < SMALL_SAMPLE else f" (n={s['n']})"))


def _research_lines(research: dict[str, Any] | None, weekly: bool) -> list[str]:
    if not research:
        return ["  Research registry unavailable: nothing reported."]
    lines = []
    for key, label in (("new", "New strategies registered"), ("testing", "Currently being tested"), ("promoted", "Promoted"),
                       ("demoted", "Demoted"), ("rejected", "Rejected / archived")):
        items = research.get(key) or []
        if weekly or key in ("new", "promoted", "demoted"):
            lines.append(f"  {label}: " + (", ".join(str(i.get("name", i)) if isinstance(i, dict) else str(i) for i in items[:12]) if items else "none")
                         + (f" (+{len(items) - 12} more)" if len(items) > 12 else ""))
    counts = research.get("counts")
    if counts:
        lines.append("  Registry: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for note in (research.get("discoveries") or [])[:5] if weekly else []:
        lines.append(f"  • {note} (backtest: simulated)")
    return lines


def _health_lines(report: dict[str, Any]) -> list[str]:
    up, health, d = report["uptime"], report.get("health") or {}, report["delivery"]
    lines = [f"  Engine uptime: {_pct(up['coverage'])} (offline ≈ {up['offline_hours']} h)"
             + (f"; {up['unmeasured_hours']} h unmeasured (before heartbeat logging began)" if up.get("unmeasured_hours") else "")]
    if health:
        lines.append("  Now: scanner " + str(health.get("scanner", "?")) + ", MT5 " + str(health.get("mt5", "?"))
                     + ", strategy bank " + str(health.get("bank", "?")) + ", outcome tracking " + str(health.get("outcomes", "?")))
    lines.append(f"  Telegram: signal alerts {d['live_alerts']['sent']} sent / {d['live_alerts']['failed']} failed; "
                 f"bank alerts {d['bank_alerts']['sent']} sent / {d['bank_alerts']['failed']} failed / {d['bank_alerts']['expired']} expired unsent")
    if d.get("previous_report"):
        p = d["previous_report"]
        lines.append(f"  Previous report {p['key']}: {p['status']}" + (" (delayed)" if p.get("delayed") else ""))
    return lines


def render_daily(report: dict[str, Any], delayed: bool = False, on_demand: bool = False) -> str:
    w = report["window"]
    head = "📊 TRADEDEN DAILY REPORT" + (" · ON DEMAND (today so far)" if on_demand else "")
    lines = [head, f"{_local(w['start'])} → {_local(w['end'])} (Kampala, EAT)"]
    if delayed:
        lines.append("⏰ DELAYED: generated after TradeDen came back online.")
    lines += ["", "SIGNALS (paper)",
              f"1. Detected (new setups, production scanners): {report['detected']}",
              f"2. Confirmed: {report['confirmed']} ({report['confirmed_production']} production, {report['confirmed_bank']} strategy bank)",
              f"3. Reached TP: {report['take_profits']}",
              f"4. Reached SL: {report['stop_losses']}" + (f"   (plus {report['time_exits']} time exits)" if report["time_exits"] else ""),
              f"5. Active (open): {report['active']}   Unresolved (ambiguous/no hit/unverifiable): {report['unresolved']}",
              f"6. Invalidated: {report['invalidated']}   Expired: {report['expired']}"
              + (f" ({report['expired_unconfirmed']} before confirmation: setup episodes closed, mostly watch setups replaced when their level moved)"
                 if report.get("expired_unconfirmed") else ""),
              f"7. Win rate (TP ÷ TP+SL): {_pct(report['win_rate'])}   Net: {report['net_r']:+.2f}R"
              + (f" ({report['expectancy']:+.2f}R per resolved signal)" if report["expectancy"] is not None else ""),
              "", "8. BY STRATEGY (outcomes realised today)"]
    lines += [_strategy_line(n, s) for n, s in report["by_strategy"].items()] or ["  No outcome realised in this window."]
    if report["confirmed_by_strategy"]:
        lines.append("  Confirmed today: " + ", ".join(f"{n} {c}" for n, c in list(report["confirmed_by_strategy"].items())[:10]))
    lines += ["", "9. BY INSTRUMENT"] + ([_strategy_line(n, s) for n, s in report["by_instrument"].items()] or ["  No outcome realised in this window."])
    best, worst = report["best"], report["worst"]
    lines += ["", "10. BEST / WORST STRATEGY", f"  Best: {best[0]} {best[1]['net_r']:+.2f}R (n={best[1]['n']})" if best else "  Best: n/a",
              f"  Worst: {worst[0]} {worst[1]['net_r']:+.2f}R (n={worst[1]['n']})" if worst else "  Worst: n/a",
              "  Daily rankings rest on very few signals: treat them as noise, not evidence.",
              "", "11-12. STRATEGY RESEARCH"] + _research_lines(report.get("research"), weekly=False)
    lines += ["", "13-14. SYSTEM HEALTH AND DELIVERY"] + _health_lines(report)
    lines += ["", "15. OBSERVATIONS"] + [f"  • {o}" for o in report["observations"]]
    lines += ["", LABELS, OFFLINE_NOTE]
    return "\n".join(lines)


def render_weekly(report: dict[str, Any], delayed: bool = False) -> str:
    w = report["window"]
    lines = ["📈 TRADEDEN WEEKLY PERFORMANCE REVIEW",
             f"{_local(w['start'])} → {_local(w['end'])} (Kampala, EAT). Cutoff 23:00: nothing after it is included."]
    if delayed:
        lines.append("⏰ DELAYED: generated after TradeDen came back online.")
    lines += ["", "A. WEEKLY PERFORMANCE (paper signals)",
              f"  Confirmed signals: {report['confirmed']} ({report['confirmed_production']} production, {report['confirmed_bank']} strategy bank)",
              f"  TP: {report['take_profits']}   SL: {report['stop_losses']}" + (f"   Time exits: {report['time_exits']}" if report["time_exits"] else ""),
              f"  Win rate: {_pct(report['win_rate'])}   Net: {report['net_r']:+.2f}R"
              + (f"   Expectancy: {report['expectancy']:+.2f}R per resolved signal" if report["expectancy"] is not None else ""),
              f"  Average planned reward-to-risk: {'n/a' if report['avg_rr'] is None else '1:' + format(report['avg_rr'], '.2f')}",
              "  By instrument:"] + ([_strategy_line(n, s) for n, s in report["by_instrument"].items()] or ["  none resolved"])
    lines += ["  By session (confirmation time):"] + ([_strategy_line(n, s) for n, s in report["by_session"].items()] or ["  none resolved"])
    board = lambda items: [f"  {i + 1}. {s['name']}: {s['expectancy']:+.2f}R/signal, WR {_pct(s['win_rate'])}, n={s['n']}"
                           + (" ⚠ small sample" if s["small"] else "") for i, s in enumerate(items)]
    lines += ["", "B. STRATEGY LEADERBOARD (this week, ranked by expectancy)"] + (board(report["top"]) or ["  No strategy resolved a signal this week."])
    if report["bottom"]:
        lines += ["  Bottom 10:"] + board(report["bottom"])
    lines += ["  Samples under 10 signals cannot separate skill from luck: rankings are provisional.",
              "  Improving: " + (", ".join(f"{t['name']} ({t['prior']:+.2f}→{t['week']:+.2f}R)" for t in report["improving"]) or "none with enough data"),
              "  Declining: " + (", ".join(f"{t['name']} ({t['prior']:+.2f}→{t['week']:+.2f}R)" for t in report["declining"]) or "none with enough data"),
              f"  Need further testing (<{SMALL_SAMPLE} resolved signals ever): " + (", ".join(report["needs_testing"][:15]) or "none")
              + (f" (+{len(report['needs_testing']) - 15} more)" if len(report["needs_testing"]) > 15 else "")]
    lines += ["", "C. STRATEGY RESEARCH"] + _research_lines(report.get("research"), weekly=True)
    c = report["correlation"]
    lines += ["", "D. RISK ANALYSIS (paper signals)",
              f"  Max drawdown this week: {report['max_drawdown_r']:.2f}R",
              f"  Longest streaks: {report['streaks']['wins']} wins, {report['streaks']['losses']} losses",
              f"  Average reward-to-risk: {'n/a' if report['avg_rr'] is None else '1:' + format(report['avg_rr'], '.2f')}",
              f"  Signal frequency: {report['signals_per_day']} per day"
              + ("; most active: " + ", ".join(f"{n} {k}" for n, k in report["frequency_by_strategy"].items()) if report["frequency_by_strategy"] else ""),
              f"  Correlation: {c['multi_strategy_opportunities']} opportunities confirmed by several strategies at once"
              + (f"; {int(c['top_instrument_share'] * 100)}% of signals on {c['top_instrument']}" if c["top_instrument_share"] else ""),
              "  Overfitting: no strategy is validated; backtest results are simulated and selected among many candidates.",
              "  Previous weeks: " + "; ".join(f"{p['week_ending']} {p['net_r']:+.1f}R ({p['tp']}/{p['sl']})" for p in report["previous_weeks"]),
              "", "E. NEXT WEEK'S RESEARCH PRIORITIES", "  Market conditions:"] + [f"  • {x}" for x in report["priorities"]["markets"]]
    lines += ["  Further validation:"] + [f"  • {x}" for x in report["priorities"]["validation"]]
    lines += ["  Strategy bank improvements:"] + [f"  • {x}" for x in report["priorities"]["improvements"]]
    lines += ["", "SYSTEM HEALTH AND DELIVERY"] + _health_lines(report) + ["", LABELS, OFFLINE_NOTE]
    return "\n".join(lines)


def render_pdf(report: dict[str, Any], text: str, rows: list[dict[str, Any]], path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    path.parent.mkdir(parents=True, exist_ok=True)
    # The PDF font has no emoji: drop characters outside the Basic Multilingual Plane.
    lines = ["".join(ch for ch in line if ord(ch) <= 0xFFFF and ch != "️") for line in text.splitlines()]
    with PdfPages(path) as pdf:
        for page_start in range(0, len(lines), 62):
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.text(0.05, 0.97, "\n".join(lines[page_start:page_start + 62]), va="top", ha="left", family="DejaVu Sans", fontsize=8, wrap=True)
            pdf.savefig(fig)
            plt.close(fig)
        end = datetime.fromisoformat(report["window"]["end"])
        resolved = [r for r in _ordered(rows) if (_parse(r["hit_at"]) or end) < end]
        if resolved:
            fig, ax = plt.subplots(figsize=(8.27, 5))
            total, xs, ys = 0.0, [], []
            for row in resolved:
                total += _r(row)
                xs.append(_parse(row["hit_at"]))
                ys.append(total)
            ax.plot(xs, ys, color="#2f6f5e")
            ax.axhline(0, color="#999", linewidth=0.8)
            ax.set_title(f"Cumulative paper R to {end.date()} (hypothetical, not trading profit)")
            fig.autofmt_xdate()
            pdf.savefig(fig)
            plt.close(fig)
    return path


# ----- ledger and scheduler ---------------------------------------------------------------------------------

class ReportLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (reports_dir() / "reports.jsonl")
        self._state: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            with self.path.open(encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("key"):
                        self._state[row["key"]] = row

    def get(self, key: str) -> dict[str, Any] | None:
        return self._state.get(key)

    def rows(self) -> list[dict[str, Any]]:
        return list(self._state.values())

    def record(self, key: str, **fields: Any) -> dict[str, Any]:
        row = {**self._state.get(key, {}), **fields, "key": key, "updated_at": datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str) + "\n")
        self._state[key] = row
        return row


def build(kind: str, start: datetime, end: datetime, sources: Sources, ledger: ReportLedger | None = None,
          delayed: bool = False, on_demand: bool = False) -> tuple[dict[str, Any], str]:
    if kind == "weekly":
        report = compute_weekly(start, end, sources, ledger)
        return report, render_weekly(report, delayed)
    report = compute_daily(start, end, sources, ledger)
    return report, render_daily(report, delayed, on_demand)


def _chunks(text: str, size: int = 3900) -> list[str]:
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > size:
            chunks.append(current)
            current = ""
        current += line
    return chunks + ([current] if current else [])


class ReportScheduler:
    def __init__(self, client: Any, chat_id: str, sources: Sources | None = None, ledger: ReportLedger | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), folder: Path | None = None,
                 pdf: bool = True) -> None:
        self.client, self.chat_id = client, str(chat_id)
        self.sources = sources or Sources()
        self.ledger = ledger or ReportLedger()
        self.clock, self.folder, self.pdf = clock, folder or reports_dir(), pdf

    def activated_at(self) -> datetime:
        meta = self.ledger.get("meta:activated")
        if meta is None:
            meta = self.ledger.record("meta:activated", activated_at=self.clock().isoformat())
        return datetime.fromisoformat(meta["activated_at"])

    def due(self) -> list[tuple[str, datetime]]:
        """Unsent due slots, oldest first; on a Friday the daily report precedes the weekly one."""
        now, activated = self.clock(), self.activated_at()
        items = [(kind, slot) for kind in ("daily", "weekly") for slot in due_slots(kind, activated, now)[-MAX_CATCH_UP[kind]:]]
        return sorted(items, key=lambda item: (item[1], KIND_ORDER[item[0]]))

    def tick(self) -> int:
        """Generate and send every due, unsent report; returns the number sent."""
        from telegram_notifier import TelegramError
        sent = 0
        now = self.clock()
        for kind, slot in self.due():
            key = f"{kind}:{slot.date().isoformat()}"
            state = self.ledger.get(key) or {}
            if state.get("status") in ("sent", "failed"):
                continue
            retry_at = _parse(state.get("retry_at"))
            if retry_at and retry_at > now:
                continue
            attempts = int(state.get("attempts") or 0)
            delayed = (now - slot) > DELAY_AFTER
            start, end = window(kind, slot)
            try:
                report, text = build(kind, start, end, self.sources, self.ledger, delayed=delayed)
                stem = self.folder / kind / slot.astimezone(KAMPALA).strftime("%Y-%m-%d")
                stem.parent.mkdir(parents=True, exist_ok=True)
                stem.with_suffix(".json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
                stem.with_suffix(".txt").write_text(text, encoding="utf-8")
                for chunk in _chunks(text):
                    self.client.send_message(self.chat_id, chunk)
                pdf = None
                if kind == "weekly" and self.pdf:
                    try:
                        pdf = render_pdf(report, text, signal_rows(self.sources), stem.with_suffix(".pdf"))
                        self.client.send_document(self.chat_id, pdf, caption=f"TradeDen weekly review to {slot.date()} (paper signals, not trades)")
                    except TelegramError:
                        raise
                    except Exception:
                        LOGGER.exception("Weekly PDF failed; the text report was sent")
            except TelegramError as exc:
                attempts += 1
                final = not exc.retryable or attempts >= 6
                self.ledger.record(key, status="failed" if final else "pending", attempts=attempts, error=str(exc),
                                   retry_at=(now + timedelta(minutes=2 ** attempts)).isoformat())
                break                 # keep the Friday order: the weekly report waits for the daily one
            self.ledger.record(key, status="sent", attempts=attempts + 1, sent_at=now.isoformat(), late=delayed,
                               window_start=start.isoformat(), window_end=end.isoformat(), pdf=str(pdf) if pdf else None)
            sent += 1
        return sent


_STATUS: dict[str, Any] = {"running": False, "last_tick_at": None, "last_error": None}


def status() -> dict[str, Any]:
    return {"enabled": enabled(), "schedule": "daily 23:00 EAT; weekly Friday 23:00 EAT (Africa/Kampala)", **_STATUS}


def heartbeat_loop(stop: threading.Event) -> None:
    """Engine uptime record (always on while the engine runs: it sends nothing)."""
    path = heartbeat_file()
    while not stop.is_set():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(datetime.now(timezone.utc).isoformat()) + "\n")
        except OSError:
            LOGGER.exception("Heartbeat write failed")
        stop.wait(HEARTBEAT_SECONDS)


def run_scheduler(stop: threading.Event, health: Callable[[], dict[str, Any]] | None = None, poll_seconds: float = 60.0) -> None:
    import telegram_notifier as tg
    try:
        client = tg.TelegramClient(os.getenv(tg.TOKEN_ENV, ""))
    except ValueError as exc:
        _STATUS["last_error"] = str(exc)
        return
    chat_id = os.getenv(tg.CHAT_ENV, "").strip()
    if not chat_id:
        _STATUS["last_error"] = f"{tg.CHAT_ENV} is not set"
        return
    scheduler = ReportScheduler(client, chat_id, Sources(health=health) if health else None)
    _STATUS["running"] = True
    try:
        while not stop.is_set():
            try:
                scheduler.tick()
                _STATUS.update(last_tick_at=datetime.now(timezone.utc).isoformat(), last_error=None)
            except Exception as exc:
                _STATUS["last_error"] = type(exc).__name__
                LOGGER.exception("Report scheduler tick failed")
            stop.wait(poll_seconds)
    finally:
        _STATUS["running"] = False
        client.close()


# ----- on-demand CLI ----------------------------------------------------------------------------------------

def _cli() -> None:
    """python reports.py preview daily|weekly    print the report the engine computes now
       python reports.py send-now daily           send today's report so far (labelled on demand)"""
    import sys
    import urllib.request
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
    if len(sys.argv) < 3 or sys.argv[1] not in ("preview", "send-now") or sys.argv[2] not in ("daily", "weekly"):
        raise SystemExit(_cli.__doc__)
    command, kind = sys.argv[1], sys.argv[2]
    engine = os.getenv("TRADEDEN_ENGINE_URL", "http://127.0.0.1:8000")
    with urllib.request.urlopen(f"{engine}/api/reports/preview?kind={kind}", timeout=600) as response:
        payload = json.load(response)
    text = payload["text"]
    if command == "preview":
        print(text)
        return
    import telegram_notifier as tg
    client = tg.TelegramClient(os.getenv(tg.TOKEN_ENV, ""))
    ledger = ReportLedger()
    key = f"adhoc:{kind}:{datetime.now(timezone.utc).isoformat()}"
    try:
        ids = [client.send_message(os.getenv(tg.CHAT_ENV, "").strip(), chunk).get("message_id") for chunk in _chunks(text)]
    except tg.TelegramError as exc:
        ledger.record(key, status="failed", error=str(exc))
        raise SystemExit(f"NOT delivered: {exc}")
    finally:
        client.close()
    ledger.record(key, status="sent", message_ids=ids, window_start=payload["report"]["window"]["start"],
                  window_end=payload["report"]["window"]["end"])
    print(f"Delivered: {len(ids)} message(s), message_id(s) {ids}")


if __name__ == "__main__":
    _cli()
