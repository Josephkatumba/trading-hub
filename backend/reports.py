"""Daily and weekly TRADEden performance reports over Telegram (T-032 Phases 5-7).

Source of truth: the authoritative signal outcomes (signal_outcomes.py) of LIVE, non-shadow
strategies; the new-confirmation count comes from setup_confirmations.jsonl. Every figure
is THEORETICAL signal performance (first barrier reached by the confirmed plan, spread in
the fills, no commission) and is labelled as such, never as trading profit.

Schedule (Africa/Kampala, UTC+3):
  daily   Monday-Friday 23:00. Window: since the previous daily slot (Monday's covers Friday
          23:00 -> Monday 23:00, so weekend crypto signals are never dropped)
  weekly  Sunday 19:00. Window: the previous Sunday 19:00 -> this Sunday 19:00. Text summary
          plus a PDF, both sent through the existing bot

Reliability: reports are keyed by (kind, slot) in reports.jsonl, so a restart never sends
one twice; slots missed while the engine was off are generated when it comes back (at
most MAX_CATCH_UP per kind, marked late). Nothing is sent for slots before the scheduler
was first activated. Reports and PDFs are kept in <data dir>/reports.

Engine uptime: the scheduler appends a heartbeat every HEARTBEAT_SECONDS to
engine_heartbeat.jsonl; uptime coverage of each window is reported, because TRADEden
cannot scan markets or send anything while the laptop or engine is off.
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
DAILY_AT, WEEKLY_AT = time(23, 0), time(19, 0)
ENABLED_ENV = "TRADEDEN_TELEGRAM_REPORTS_ENABLED"
HEARTBEAT_SECONDS = 60
MAX_CATCH_UP = {"daily": 5, "weekly": 2}
DECISIVE = ("TARGET_HIT", "STOP_HIT")
THEORETICAL = ("Theoretical signal results: the first level each confirmed plan reached, spread included, "
               "commission excluded. Not trading profit; TRADEden executes no trades.")
OFFLINE_NOTE = "TRADEden cannot scan markets or send alerts while the laptop or engine is offline."
STRATEGY_NAMES = {"trendline_v5": "Trendline", "support_resistance": "Support & Resistance",
                  "trend_momentum": "Trend / Momentum", "smc": "Smart Money Concepts"}


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


# ----- schedule ---------------------------------------------------------------------------------

def daily_slot(day: date) -> datetime:
    return datetime.combine(day, DAILY_AT, KAMPALA)


def weekly_slot(day: date) -> datetime:
    return datetime.combine(day, WEEKLY_AT, KAMPALA)


def due_slots(kind: str, after: datetime, now: datetime) -> list[datetime]:
    """Slots of `kind` in (after, now], oldest first."""
    slots = []
    day = after.astimezone(KAMPALA).date()
    while True:
        if kind == "daily" and day.weekday() < 5:
            slot = daily_slot(day)
        elif kind == "weekly" and day.weekday() == 6:
            slot = weekly_slot(day)
        else:
            slot = None
        if slot is not None and slot > now:
            break
        if slot is not None and slot > after:
            slots.append(slot)
        day += timedelta(days=1)
        if day > now.astimezone(KAMPALA).date() + timedelta(days=1):
            break
    return slots


def window(kind: str, slot: datetime) -> tuple[datetime, datetime]:
    if kind == "weekly":
        return slot - timedelta(days=7), slot
    previous = slot.astimezone(KAMPALA).date() - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return daily_slot(previous), slot


# ----- data -------------------------------------------------------------------------------------------

def live_strategy_ids() -> set[str]:
    from strategies import REGISTRY
    return set(REGISTRY.live())


def session_of(instant: datetime) -> str:
    london, ny = instant.astimezone(LONDON).time(), instant.astimezone(NEW_YORK).time()
    in_london, in_ny = time(8) <= london < time(16, 30), time(8) <= ny < time(17)
    return "London/NY overlap" if in_london and in_ny else "London" if in_london else "New York" if in_ny else "Asia/off-hours"


def uptime(start: datetime, end: datetime, beats: Iterable[datetime]) -> dict[str, Any]:
    """Share of [start, end) covered by heartbeats (a beat covers the following 2 minutes).
    Time before the first heartbeat ever recorded is not measured (None), never "offline"."""
    beats = list(beats)
    first = min(beats) if beats else None
    if first is None or first >= end:
        return {"coverage": None, "offline_hours": None, "measured_from": None}
    measured_from = max(start, first)
    if measured_from > start:
        part = uptime(measured_from, end, beats)
        return {**part, "measured_from": measured_from.isoformat()}
    covered, cursor = 0.0, start
    for beat in sorted(b for b in beats if start - timedelta(minutes=2) <= b < end):
        lo, hi = max(beat, cursor), min(end, beat + timedelta(seconds=2 * HEARTBEAT_SECONDS))
        if hi > lo:
            covered += (hi - lo).total_seconds()
            cursor = hi
    total = (end - start).total_seconds()
    return {"coverage": round(covered / total, 4) if total else None, "offline_hours": round((total - covered) / 3600, 1),
            "measured_from": start.isoformat()}


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


def _r(row: dict[str, Any]) -> float:
    return float(row.get("r_multiple") or 0.0) if row.get("status") in DECISIVE else 0.0


def _group(rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    out = {}
    for name, items in groups.items():
        wins = sum(r["status"] == "TARGET_HIT" for r in items)
        losses = sum(r["status"] == "STOP_HIT" for r in items)
        out[name] = {"tp": wins, "sl": losses, "other": len(items) - wins - losses,
                     "net_r": round(sum(_r(r) for r in items), 2),
                     "win_rate": round(wins / (wins + losses), 3) if wins + losses else None}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["net_r"]))


def _drawdown(rows: list[dict[str, Any]]) -> float:
    peak = equity = worst = 0.0
    for row in sorted(rows, key=lambda r: str(r.get("hit_at"))):
        equity += _r(row)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def compute(kind: str, slot: datetime, outcomes: list[dict[str, Any]], confirmations: list[dict[str, Any]],
            beats: list[datetime], live: set[str]) -> dict[str, Any]:
    start, end = window(kind, slot)
    live_rows = [r for r in outcomes if r.get("strategy_id") in live and not r.get("shadow")]

    def within(value: Any) -> bool:
        stamp = _parse(value)
        return stamp is not None and start <= stamp < end

    confirmed = [c for c in confirmations if c.get("shadow") is not True and (c.get("strategy_id") or "trendline") in live
                 and within(c.get("confirmed_at"))]
    # An outcome is "realised" in the window when its level was reached in it; final outcomes
    # without a hit time (ambiguous/unavailable/no hit) count when they were recorded in it.
    realised = [r for r in live_rows if r.get("status") in DECISIVE and within(r.get("hit_at"))]
    undecided = [r for r in live_rows if r.get("status") in ("AMBIGUOUS", "UNAVAILABLE", "NO_HIT")
                 and within(r.get("hit_at") or r.get("recorded_at"))]
    active = [r for r in live_rows if r.get("status") == "PENDING" and (_parse(r.get("confirmed_at")) or end) < end]
    wins = sum(r["status"] == "TARGET_HIT" for r in realised)
    losses = len(realised) - wins
    net = round(sum(_r(r) for r in realised), 2)
    by_strategy = _group(realised, lambda r: STRATEGY_NAMES.get(r["strategy_id"], r["strategy_id"]))
    report: dict[str, Any] = {
        "kind": kind, "slot": slot.isoformat(), "window": {"start": start.isoformat(), "end": end.isoformat()},
        "new_confirmed": len(confirmed),
        "new_confirmed_list": [{"symbol": c.get("symbol"), "side": {"LONG": "BUY", "SHORT": "SELL"}.get(c.get("direction"), "?"),
                                "strategy": STRATEGY_NAMES.get(c.get("strategy_id"), c.get("strategy_id")),
                                "score": c.get("score"), "confirmed_at": c.get("confirmed_at")} for c in confirmed],
        "take_profits": wins, "stop_losses": losses, "active": len(active),
        "ambiguous": sum(r["status"] == "AMBIGUOUS" for r in undecided),
        "unavailable": sum(r["status"] == "UNAVAILABLE" for r in undecided),
        "no_hit": sum(r["status"] == "NO_HIT" for r in undecided),
        "win_rate": round(wins / (wins + losses), 3) if wins + losses else None,
        "net_r": net, "expectancy_r": round(net / (wins + losses), 3) if wins + losses else None,
        "by_strategy": by_strategy, "by_instrument": _group(realised, lambda r: str(r.get("symbol"))),
        "uptime": uptime(start, end, beats),
    }
    ranked = [(name, g) for name, g in by_strategy.items() if g["tp"] + g["sl"]]
    report["best_strategy"] = ranked[0][0] if ranked else None
    report["worst_strategy"] = ranked[-1][0] if len(ranked) > 1 else None
    report["observations"] = observations(report, realised)
    if kind == "weekly":
        report["by_session"] = _group(realised, lambda r: session_of(_parse(r["confirmed_at"])))
        report["by_setup"] = _group(realised, lambda r: f"{STRATEGY_NAMES.get(r['strategy_id'], r['strategy_id'])} {r.get('direction', '')}")
        report["max_drawdown_r"] = _drawdown(realised)
        resolved_all = [r for r in live_rows if r.get("status") in DECISIVE and (_parse(r.get("hit_at")) or end) < end]
        report["cumulative_r"] = round(sum(_r(r) for r in resolved_all), 2)
        report["cumulative_trades"] = len(resolved_all)
        report["previous_weeks"] = []
        for back in range(1, 5):
            ws, we = start - timedelta(days=7 * back), end - timedelta(days=7 * back)
            rows = [r for r in live_rows if r.get("status") in DECISIVE and ws <= (_parse(r.get("hit_at")) or ws - timedelta(1)) < we]
            w = sum(r["status"] == "TARGET_HIT" for r in rows)
            report["previous_weeks"].append({"week_ending": we.date().isoformat(), "tp": w, "sl": len(rows) - w,
                                             "net_r": round(sum(_r(r) for r in rows), 2)})
        report["data_quality"] = {"pending": len(active), "ambiguous": report["ambiguous"],
                                  "unavailable": report["unavailable"], "no_hit": report["no_hit"]}
        report["recommendations"] = recommendations(report, live_rows, end)
    return report


def observations(report: dict[str, Any], realised: list[dict[str, Any]]) -> list[str]:
    notes = []
    offline = report["uptime"]["offline_hours"] or 0
    if offline and offline >= 0.5:
        notes.append(f"Engine offline for about {offline} h in this window: no signals could be detected or sent then.")
    for symbol, g in report["by_instrument"].items():
        if g["sl"] >= 3 and g["tp"] == 0:
            notes.append(f"{symbol}: {g['sl']} stops and no targets in this window.")
    fast = [r for r in realised if r["status"] == "STOP_HIT" and (r.get("hours_to_hit") or 99) <= 1]
    if len(fast) >= 2:
        notes.append(f"{len(fast)} stops were hit within an hour of confirmation.")
    if report["ambiguous"] or report["unavailable"]:
        notes.append(f"{report['ambiguous']} ambiguous and {report['unavailable']} unverifiable outcomes are excluded from win rate and R.")
    if not report["new_confirmed"] and not offline:
        notes.append("No setup passed confirmation in this window; that is a valid outcome, not a fault.")
    return notes


def recommendations(report: dict[str, Any], live_rows: list[dict[str, Any]], end: datetime) -> list[str]:
    """Evidence-based prompts for the coming week (trailing 4 weeks, minimum samples)."""
    recs = []
    since = end - timedelta(days=28)
    recent = [r for r in live_rows if r.get("status") in DECISIVE and since <= (_parse(r.get("hit_at")) or since - timedelta(1)) < end]
    for name, g in _group(recent, lambda r: r["strategy_id"]).items():
        n = g["tp"] + g["sl"]
        if n >= 10 and g["net_r"] < 0:
            recs.append(f"{STRATEGY_NAMES.get(name, name)}: {g['net_r']:+.1f}R over {n} resolved signals in 4 weeks; "
                        "review it in the research lab before relying on its alerts.")
        elif n < 10:
            recs.append(f"{STRATEGY_NAMES.get(name, name)}: only {n} resolved signals in 4 weeks; too few to judge.")
    for symbol, g in _group(recent, lambda r: str(r.get("symbol"))).items():
        if g["tp"] + g["sl"] >= 12 and g["win_rate"] is not None and g["win_rate"] < 0.2:
            recs.append(f"{symbol}: {g['tp']} target(s) vs {g['sl']} stop(s) over 4 weeks; worth watching "
                        "(per-instrument samples are small, so this is not yet evidence).")
    if report["uptime"]["coverage"] is not None and report["uptime"]["coverage"] < 0.9:
        recs.append("Keep the engine running through the trading week; downtime leaves gaps in signals and alerts.")
    return recs or ["No change suggested: samples are within normal variation."]


# ----- rendering ------------------------------------------------------------------------------------

def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _kampala(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(KAMPALA).strftime("%a %d %b %H:%M")


def render_text(report: dict[str, Any], late: bool = False) -> str:
    kind = report["kind"]
    w = report["window"]
    lines = ["📊 TRADEDEN " + ("DAILY" if kind == "daily" else "WEEKLY") + " PERFORMANCE",
             f"{_kampala(w['start'])} → {_kampala(w['end'])} (Kampala time)"]
    if late:
        lines.append("⚠️ Late: generated after the engine came back online.")
    lines += ["", "CONFIRMED IN THIS WINDOW", f"New confirmed signals: {report['new_confirmed']}"]
    for c in report["new_confirmed_list"][:8]:
        lines.append(f"  • {c['symbol']} {c['side']} · {c['strategy']} · score {c['score']}")
    if len(report["new_confirmed_list"]) > 8:
        lines.append(f"  … and {len(report['new_confirmed_list']) - 8} more")
    lines += ["", "OUTCOMES REALISED IN THIS WINDOW (any confirmation date)",
              f"Take profits: {report['take_profits']}   Stop losses: {report['stop_losses']}",
              f"Win rate (resolved): {_pct(report['win_rate'])}",
              f"Net theoretical R: {report['net_r']:+.2f}R" + (f" ({report['expectancy_r']:+.2f}R per signal)" if report["expectancy_r"] is not None else ""),
              f"Ambiguous: {report['ambiguous']}   Unverifiable: {report['unavailable']}   No hit in 7 days: {report['no_hit']}",
              f"Signals still active: {report['active']}"]
    if report["best_strategy"]:
        lines.append(f"Best strategy: {report['best_strategy']}" + (f"   Worst: {report['worst_strategy']}" if report["worst_strategy"] else ""))
    if report["by_instrument"]:
        lines += ["", "BY INSTRUMENT"]
        lines += [f"  {s}: {g['tp']} TP / {g['sl']} SL, {g['net_r']:+.2f}R" for s, g in report["by_instrument"].items()]
    if kind == "weekly":
        lines += ["", "BY STRATEGY"] + [f"  {s}: {g['tp']} TP / {g['sl']} SL, {g['net_r']:+.2f}R, win {_pct(g['win_rate'])}"
                                        for s, g in report["by_strategy"].items()]
        lines += ["", "BY SESSION (confirmation time)"] + [f"  {s}: {g['tp']} TP / {g['sl']} SL, {g['net_r']:+.2f}R"
                                                            for s, g in report["by_session"].items()]
        lines += ["", f"Max theoretical drawdown this week: {report['max_drawdown_r']:.2f}R",
                  f"Cumulative theoretical R (all tracked signals): {report['cumulative_r']:+.2f}R over {report['cumulative_trades']}",
                  "Previous weeks: " + "; ".join(f"{p['week_ending']} {p['net_r']:+.1f}R ({p['tp']}/{p['sl']})" for p in report["previous_weeks"]),
                  "", "RECOMMENDATIONS"] + [f"  • {r}" for r in report["recommendations"]]
    up = report["uptime"]
    lines += ["", "OBSERVATIONS"] + [f"  • {o}" for o in report["observations"]] if report["observations"] else []
    if up["coverage"] is None:
        uptime_line = "Engine uptime in window: not measured (no uptime record yet)."
    else:
        since = "" if up["measured_from"] == w["start"] else f" since {_kampala(up['measured_from'])}"
        uptime_line = f"Engine uptime in window{since}: {_pct(up['coverage'])} (offline ≈ {up['offline_hours']} h)."
    lines += ["", f"{uptime_line} {OFFLINE_NOTE}",
              THEORETICAL]
    return "\n".join(lines)


def render_pdf(report: dict[str, Any], outcomes: list[dict[str, Any]], path: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    path.parent.mkdir(parents=True, exist_ok=True)
    # The PDF font has no emoji: drop characters outside the Basic Multilingual Plane.
    text = ["".join(ch for ch in line if ord(ch) <= 0xFFFF and ch != "️").strip() if i == 0 else
            "".join(ch for ch in line if ord(ch) <= 0xFFFF and ch != "️")
            for i, line in enumerate(render_text(report).splitlines())]
    with PdfPages(path) as pdf:
        for page_start in range(0, len(text), 58):
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.text(0.06, 0.97, "\n".join(text[page_start:page_start + 58]), va="top", ha="left", family="DejaVu Sans",
                     fontsize=8.5, wrap=True)
            pdf.savefig(fig)
            plt.close(fig)
        end = datetime.fromisoformat(report["window"]["end"])
        rows = sorted((r for r in outcomes if r.get("status") in DECISIVE and (_parse(r.get("hit_at")) or end) < end),
                      key=lambda r: r["hit_at"])
        if rows:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.27, 11.69))
            by: dict[str, list[float]] = defaultdict(list)
            total, xs, ys = 0.0, [], []
            for row in rows:
                total += _r(row)
                xs.append(_parse(row["hit_at"]))
                ys.append(total)
                by[STRATEGY_NAMES.get(row["strategy_id"], row["strategy_id"])].append(_r(row))
            ax1.plot(xs, ys, color="#2f6f5e")
            ax1.axhline(0, color="#999", linewidth=0.8)
            ax1.set_title(f"Cumulative theoretical R to {end.date()}, live strategies (not trading profit)")
            for label in ax1.get_xticklabels():
                label.set_rotation(30)
                label.set_horizontalalignment("right")
            ax1.set_ylabel("R")
            names = list(by)
            ax2.bar(names, [sum(v) for v in by.values()], color=["#2f6f5e" if sum(v) >= 0 else "#c0504d" for v in by.values()])
            ax2.set_title(f"Theoretical R by strategy, all tracked signals to {end.date()}")
            ax2.tick_params(axis="x", rotation=15)
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)
        info = pdf.infodict()
        info["Title"] = f"TRADEden weekly performance {report['slot'][:10]}"
    return path


# ----- ledger and scheduler ----------------------------------------------------------------------------

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

    def record(self, key: str, **fields: Any) -> dict[str, Any]:
        row = {**self._state.get(key, {}), **fields, "key": key, "updated_at": datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str) + "\n")
        self._state[key] = row
        return row


class ReportScheduler:
    def __init__(self, client: Any, chat_id: str, ledger: ReportLedger | None = None,
                 outcomes: Callable[[], list[dict[str, Any]]] | None = None,
                 confirmations: Callable[[], list[dict[str, Any]]] | None = None,
                 beats: Callable[[], list[datetime]] = heartbeats, live: Callable[[], set[str]] = live_strategy_ids,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), folder: Path | None = None) -> None:
        if outcomes is None:
            import signal_outcomes
            outcomes = lambda: signal_outcomes.OutcomeStore().all_latest()
        if confirmations is None:
            from observations import confirmation_events
            confirmations = confirmation_events
        self.client, self.chat_id = client, str(chat_id)
        self.ledger = ledger or ReportLedger()
        self.outcomes, self.confirmations, self.beats, self.live, self.clock = outcomes, confirmations, beats, live, clock
        self.folder = folder or reports_dir()

    def activated_at(self) -> datetime:
        meta = self.ledger.get("meta:activated")
        if meta is None:
            meta = self.ledger.record("meta:activated", activated_at=self.clock().isoformat())
        return datetime.fromisoformat(meta["activated_at"])

    def generate(self, kind: str, slot: datetime) -> tuple[dict[str, Any], str, Path | None]:
        outcomes = self.outcomes()
        report = compute(kind, slot, outcomes, self.confirmations(), self.beats(), self.live())
        late = (self.clock() - slot) > timedelta(minutes=15)
        text = render_text(report, late)
        stem = self.folder / kind / slot.astimezone(KAMPALA).strftime("%Y-%m-%d")
        stem.parent.mkdir(parents=True, exist_ok=True)
        stem.with_suffix(".json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        stem.with_suffix(".txt").write_text(text, encoding="utf-8")
        pdf = render_pdf(report, [r for r in outcomes if r.get("strategy_id") in self.live()], stem.with_suffix(".pdf")) if kind == "weekly" else None
        return report, text, pdf

    def tick(self) -> int:
        """Generate and send every due, unsent slot; returns the number sent."""
        from telegram_notifier import TelegramError
        sent = 0
        now = self.clock()
        activated = self.activated_at()
        for kind in ("daily", "weekly"):
            slots = due_slots(kind, activated, now)[-MAX_CATCH_UP[kind]:]
            for slot in slots:
                key = f"{kind}:{slot.date().isoformat()}"
                state = self.ledger.get(key) or {}
                if state.get("status") in ("sent", "failed"):
                    continue
                attempts = int(state.get("attempts") or 0)
                retry_at = _parse(state.get("retry_at"))
                if retry_at and retry_at > now:
                    continue
                try:
                    report, text, pdf = self.generate(kind, slot)
                    for chunk in _chunks(text):
                        self.client.send_message(self.chat_id, chunk)
                    if pdf is not None:
                        self.client.send_document(self.chat_id, pdf, caption=f"TRADEden weekly report {slot.date()} (theoretical results)")
                except TelegramError as exc:
                    attempts += 1
                    final = not exc.retryable or attempts >= 6
                    self.ledger.record(key, status="failed" if final else "pending", attempts=attempts, error=str(exc),
                                       retry_at=(now + timedelta(minutes=2 ** attempts)).isoformat())
                    continue
                self.ledger.record(key, status="sent", attempts=attempts + 1, sent_at=now.isoformat(),
                                   late=(now - slot) > timedelta(minutes=15), pdf=str(pdf) if pdf else None)
                sent += 1
        return sent


def _chunks(text: str, size: int = 3900) -> list[str]:
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > size:
            chunks.append(current)
            current = ""
        current += line
    return chunks + ([current] if current else [])


_STATUS: dict[str, Any] = {"running": False, "last_tick_at": None, "last_error": None}


def status() -> dict[str, Any]:
    return {"enabled": enabled(), **_STATUS}


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


def run_scheduler(stop: threading.Event, poll_seconds: float = 60.0) -> None:
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
    scheduler = ReportScheduler(client, chat_id)
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
