"""Authoritative outcome of every confirmed signal (T-032 Phase 4).

One record per confirmed opportunity (setup_id), resolved from MT5 history, so engine
downtime no longer loses outcomes: candles are fetched for the whole path whenever the
resolver runs, not only from the scan's recent window. The existing per-horizon research
labels (market_outcomes.jsonl) are left unchanged.

Resolution, for the plan the signal was confirmed with (observations.confirmed_plan):
  path      from the confirmation instant to TRACK_DAYS later
  first bar the remainder of the confirmation's M15 candle is read from M1 bars after the
            confirmation minute. Without M1 it is accepted only when the WHOLE candle touched
            neither level (then the remainder cannot have); otherwise the outcome is
            UNAVAILABLE (the first minutes are unknown)
  fills     MT5 bars are bid: a BUY exits at the bid (SL low <= SL, TP high >= TP); a SELL at
            the ask (bid + the bar's recorded spread), as the executable qualification assumes
  ties      an M15 candle touching both levels is replayed on M1; a minute touching both, or
            no M1 coverage, is AMBIGUOUS (explicit, never guessed)
  statuses  TARGET_HIT / STOP_HIT / AMBIGUOUS / NO_HIT (window ended) / PENDING (still open) /
            UNAVAILABLE (no plan, or history insufficient to verify)

Store: signal_outcomes.jsonl, append-only. The latest revision per setup_id is
authoritative. A changed result is appended as a new revision with `supersedes` and
`correction_reason` (auditable); an identical result is never re-written (no duplicates).
"""
from __future__ import annotations

import bisect
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from market_time import normalize_mt5_epoch
from storage_config import data_directory

LOGGER = logging.getLogger("trading_hub.signal_outcomes")
RESOLVER_VERSION = "signal-outcome-v1"
TRACK_DAYS = 7
FINAL = ("TARGET_HIT", "STOP_HIT", "AMBIGUOUS", "NO_HIT", "UNAVAILABLE")
M15_SECONDS = 900

Fetch = Callable[[str, str, datetime, datetime], "list[dict[str, Any]] | None"]


def outcomes_file() -> Path:
    return data_directory() / "signal_outcomes.jsonl"


# ----- resolution (pure) -------------------------------------------------------------------------

def _touch(long: bool, bar: dict[str, Any], sl: float, tp: float) -> tuple[bool, bool]:
    spread = float(bar.get("spread") or 0.0)
    if long:
        return bar["low"] <= sl, bar["high"] >= tp
    return bar["high"] + spread >= sl, bar["low"] + spread <= tp


def _first_in(long: bool, minutes: list[dict[str, Any]], sl: float, tp: float) -> tuple[str | None, dict | None]:
    """('SL'|'TP'|'BOTH'|None, bar) for the first minute touching a level."""
    for bar in minutes:
        stop, target = _touch(long, bar, sl, tp)
        if stop and target:
            return "BOTH", bar
        if stop or target:
            return ("SL" if stop else "TP"), bar
    return None, None


def resolve(plan: dict[str, Any], confirmed_at: datetime, m15: list[dict[str, Any]], m1: list[dict[str, Any]] | None,
            now: datetime, track_days: int = TRACK_DAYS) -> dict[str, Any]:
    """The outcome of one plan from UTC-normalised bars (`utc` epoch seconds, bid OHLC, spread in price)."""
    direction = plan.get("direction")
    try:
        entry, sl, tp = float(plan["entry"]), float(plan["stop_loss"]), float(plan["take_profit"])
    except (KeyError, TypeError, ValueError):
        return {"status": "UNAVAILABLE", "reason": "confirmed plan incomplete"}
    long = direction == "LONG"
    if direction not in ("LONG", "SHORT") or not ((sl < entry < tp) if long else (tp < entry < sl)):
        return {"status": "UNAVAILABLE", "reason": "confirmed plan levels inconsistent"}
    start = confirmed_at.timestamp()
    end = min((confirmed_at + timedelta(days=track_days)).timestamp(), now.timestamp())
    m1 = sorted(m1 or [], key=lambda b: b["utc"])
    m1_times = [b["utc"] for b in m1]
    m15 = sorted(m15, key=lambda b: b["utc"])
    first_open = start - (start % M15_SECONDS)
    evidence: dict[str, Any] = {"m15_bars": 0, "m1_bars_used": 0, "first_bar": None, "last_bar_checked": None}

    def done(status: str, at: float | None, method: str, reason: str) -> dict[str, Any]:
        risk = abs(entry - sl)
        r = (abs(tp - entry) / risk if status == "TARGET_HIT" else -1.0 if status == "STOP_HIT" else None)
        return {"status": status, "hit_at": datetime.fromtimestamp(at, timezone.utc).isoformat() if at else None,
                "hours_to_hit": round((at - start) / 3600, 2) if at else None, "method": method, "reason": reason,
                "r_multiple": round(r, 4) if r is not None else None, "evidence": evidence}

    # 1) the rest of the confirmation candle
    minute_after = start - (start % 60) + 60
    lo, hi = bisect.bisect_left(m1_times, minute_after), bisect.bisect_left(m1_times, first_open + M15_SECONDS)
    partial = m1[lo:hi]
    covered = bool(m1) and m1_times[0] <= first_open and (hi > lo or first_open + M15_SECONDS <= minute_after)
    first_bar = next((b for b in m15 if b["utc"] == first_open), None)
    if covered:
        evidence["m1_bars_used"] += len(partial)
        hit, bar = _first_in(long, partial, sl, tp)
        if hit == "BOTH":
            return done("AMBIGUOUS", bar["utc"], "M1", "stop and target inside one minute of the confirmation candle")
        if hit:
            return done("STOP_HIT" if hit == "SL" else "TARGET_HIT", bar["utc"], "M1", "first level reached in the confirmation candle")
    elif first_bar is not None:
        stop, target = _touch(long, first_bar, sl, tp)
        if stop or target:
            return done("UNAVAILABLE", None, "M15", "the confirmation candle touched a level and no M1 history covers its remaining minutes")
    else:
        return done("UNAVAILABLE", None, "M15", "the confirmation candle is missing from MT5 history")
    evidence["first_bar"] = datetime.fromtimestamp(first_open, timezone.utc).isoformat()

    # 2) every later M15 candle, in order
    later = [b for b in m15 if first_open + M15_SECONDS <= b["utc"] < end]
    if not later and end - first_open > 2 * M15_SECONDS and end < now.timestamp():
        return done("UNAVAILABLE", None, "M15", "no MT5 candles after the confirmation")
    previous = first_open
    max_gap = 0.0
    for bar in later:
        max_gap = max(max_gap, bar["utc"] - previous)
        previous = bar["utc"]
        evidence["m15_bars"] += 1
        evidence["last_bar_checked"] = datetime.fromtimestamp(bar["utc"], timezone.utc).isoformat()
        stop, target = _touch(long, bar, sl, tp)
        if stop and target:
            a, b = bisect.bisect_left(m1_times, bar["utc"]), bisect.bisect_left(m1_times, bar["utc"] + M15_SECONDS)
            hit, minute = _first_in(long, m1[a:b], sl, tp) if b > a else (None, None)
            evidence["m1_bars_used"] += b - a
            if hit in ("SL", "TP"):
                return done("STOP_HIT" if hit == "SL" else "TARGET_HIT", minute["utc"], "M1",
                            "both levels inside one M15 candle; M1 replay decided the order")
            return done("AMBIGUOUS", bar["utc"], "M15" if b == a else "M1",
                        "both levels inside one M15 candle and " + ("no M1 history covers it" if b == a else "inside one minute"))
        if stop or target:
            return done("STOP_HIT" if stop else "TARGET_HIT", bar["utc"], "M15", "first level reached")
    evidence["max_gap_hours"] = round(max_gap / 3600, 2)
    if (confirmed_at + timedelta(days=track_days)).timestamp() <= now.timestamp():
        return done("NO_HIT", None, "M15", f"neither level reached within {track_days} days")
    return done("PENDING", None, "M15", "signal still open")


# ----- store ------------------------------------------------------------------------------------------

_SEMANTIC = ("status", "hit_at", "r_multiple", "reason")


class OutcomeStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or outcomes_file()
        self._lock = threading.Lock()
        self._latest: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        if self.path.exists():
            with self.path.open("rb") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(row, dict) and row.get("setup_id"):
                        self._history.setdefault(row["setup_id"], []).append(row)
                        self._latest[row["setup_id"]] = row

    def latest(self, setup_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._latest.get(setup_id)

    def all_latest(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._latest.values())

    def history(self, setup_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history.get(setup_id, []))

    def write(self, base: dict[str, Any], result: dict[str, Any], correction_reason: str | None = None) -> dict[str, Any] | None:
        """Append a revision unless it repeats the current one; returns the new row or None."""
        with self._lock:
            current = self._latest.get(base["setup_id"])
            if current and all(current.get(k) == result.get(k) for k in _SEMANTIC):
                return None
            if current and current.get("status") in FINAL and result.get("status") == "PENDING":
                return None              # a final outcome never reverts to pending
            row = {"record_type": "signal_outcome", "schema_version": "1.0", "resolver_version": RESOLVER_VERSION,
                   "outcome_id": "sig_out_" + uuid.uuid4().hex, **base, **result,
                   "revision": (current.get("revision", 0) + 1) if current else 1,
                   "supersedes": current.get("outcome_id") if current else None,
                   "correction_reason": correction_reason if current else None,
                   "recorded_at": datetime.now(timezone.utc).isoformat()}
            if current and row["correction_reason"] is None:
                row["correction_reason"] = ("progressed" if current.get("status") == "PENDING"
                                            else f"re-resolved: {current.get('status')} -> {result.get('status')}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as handle:
                handle.write((json.dumps(row, separators=(",", ":"), default=str) + "\n").encode("utf-8"))
            self._latest[row["setup_id"]] = row
            self._history.setdefault(row["setup_id"], []).append(row)
            return row


# ----- resolver over the engine's confirmations ------------------------------------------------------------

def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


class Resolver:
    def __init__(self, fetch: Fetch, store: OutcomeStore | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.fetch, self.store, self.clock = fetch, store or OutcomeStore(), clock

    def _base(self, confirmation: dict[str, Any], snapshot: dict[str, Any] | None, plan: dict[str, Any]) -> dict[str, Any]:
        from strategies import record_strategy_id
        return {"setup_id": str(confirmation["setup_id"]), "observation_id": confirmation.get("observation_id"),
                "confirmation_event_id": confirmation.get("confirmation_event_id"),
                "confirmed_at": confirmation.get("confirmed_at"), "symbol": confirmation.get("symbol"),
                "broker_symbol": (snapshot or {}).get("broker_symbol"), "strategy_id": record_strategy_id(confirmation),
                "strategy_version": confirmation.get("strategy_version"), "shadow": confirmation.get("shadow") is True,
                "direction": plan.get("direction") or confirmation.get("direction"), "score": confirmation.get("score"),
                "timeframe": (snapshot or {}).get("timeframe"), "entry": plan.get("entry"),
                "stop_loss": plan.get("stop_loss"), "take_profit": plan.get("take_profit")}

    def resolve_one(self, confirmation: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        from observations import confirmed_plan
        plan = confirmed_plan(snapshot) or {}
        base = self._base(confirmation, snapshot, plan)
        confirmed_at = _parse(confirmation.get("confirmed_at"))
        now = self.clock()
        if snapshot is None or confirmed_at is None:
            return self.store.write(base, {"status": "UNAVAILABLE", "reason": "confirmation snapshot or time missing",
                                           "method": None, "hit_at": None, "r_multiple": None})
        broker = snapshot.get("broker_symbol") or confirmation.get("symbol")
        end = min(now, confirmed_at + timedelta(days=TRACK_DAYS))
        m15 = self.fetch(broker, "M15", confirmed_at - timedelta(minutes=15), end)
        if m15 is None:
            return None          # MT5 unreachable: try again later, nothing is guessed
        m1 = self.fetch(broker, "M1", confirmed_at - timedelta(minutes=1), end) or []
        return self.store.write(base, resolve(plan, confirmed_at, m15, m1, now))

    def run(self, confirmations: list[dict[str, Any]], snapshot_for: Callable[[str], dict[str, Any] | None],
            limit: int | None = None) -> int:
        """Resolve confirmations that are not final yet; returns the number of new revisions."""
        written = 0
        for confirmation in confirmations:
            current = self.store.latest(str(confirmation.get("setup_id")))
            if current and current.get("status") in FINAL:
                continue
            row = self.resolve_one(confirmation, snapshot_for(str(confirmation.get("observation_id"))))
            written += row is not None
            if limit is not None and written >= limit:
                break
        return written


def mt5_fetch(mt5: Any, ensure: Callable[[], tuple[bool, str | None]], basis: str | None) -> Fetch:
    """A Fetch over the engine's MT5 session: UTC-normalised bars, or None when MT5 is offline."""
    def fetch(broker_symbol: str, timeframe: str, start: datetime, end: datetime) -> list[dict[str, Any]] | None:
        ok, _ = ensure()
        if not ok or not basis:
            return None
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            return None
        code = getattr(mt5, f"TIMEFRAME_{timeframe}")
        pad = timedelta(days=1)
        rates = mt5.copy_rates_range(broker_symbol, code, (start - pad).replace(tzinfo=None), (end + pad).replace(tzinfo=None))
        if rates is None:
            return [] if timeframe == "M1" else None
        bars = []
        for rate in rates:
            stamp = normalize_mt5_epoch(int(rate["time"]), basis)
            if stamp.get("normalization_status") != "VERIFIED":
                continue
            utc = datetime.fromisoformat(stamp["normalized_utc"]).timestamp()
            if start.timestamp() - 900 <= utc <= end.timestamp():
                bars.append({"utc": utc, "open": float(rate["open"]), "high": float(rate["high"]),
                             "low": float(rate["low"]), "close": float(rate["close"]),
                             "spread": int(rate["spread"]) * float(info.point)})
        return bars
    return fetch


_STATUS: dict[str, Any] = {"running": False, "last_run_at": None, "last_written": None, "last_error": None}


def status() -> dict[str, Any]:
    return dict(_STATUS)


def run_worker(stop: threading.Event, fetch: Fetch, interval_seconds: float = 300.0, batch: int = 50) -> None:
    """Resolve outstanding confirmations every few minutes, in its own thread."""
    from observations import confirmation_events, snapshots_by_observation_id
    resolver = Resolver(fetch)
    _STATUS["running"] = True
    try:
        while not stop.is_set():
            try:
                confirmations = confirmation_events()
                pending = [c for c in confirmations if (resolver.store.latest(str(c.get("setup_id"))) or {}).get("status") not in FINAL]
                snapshots = snapshots_by_observation_id(str(c.get("observation_id")) for c in pending[:batch])
                written = resolver.run(pending[:batch], snapshots.get, limit=batch)
                _STATUS.update(last_run_at=datetime.now(timezone.utc).isoformat(), last_written=written,
                               outstanding=max(0, len(pending) - batch), last_error=None)
                # Catch up quickly after downtime, then settle to the normal interval.
                stop.wait(5.0 if len(pending) > batch else interval_seconds)
                continue
            except Exception as exc:
                _STATUS["last_error"] = f"{type(exc).__name__}: {exc}"
                LOGGER.exception("Signal outcome resolution failed")
            stop.wait(interval_seconds)
    finally:
        _STATUS["running"] = False


def enabled() -> bool:
    return os.getenv("TRADEDEN_SIGNAL_OUTCOMES_ENABLED", "").strip() == "1"


def backfill(limit: int | None = None, engine_url: str | None = None) -> dict[str, int]:
    """One-off resolution of every confirmation through a separate MT5 session (CLI)."""
    import MetaTrader5 as mt5
    from collections import Counter
    from observations import confirmation_events, snapshots_by_observation_id
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        fetch = mt5_fetch(mt5, lambda: (True, None), os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE"))
        confirmations = confirmation_events()[:limit] if limit else confirmation_events()
        if engine_url:
            # The engine is running: read snapshots through its API, so this process never
            # writes the observation index sidecars the engine is using.
            import urllib.request
            snapshots: dict[str, Any] = {}
            for c in confirmations:
                with urllib.request.urlopen(f"{engine_url}/api/market/setups/{c['setup_id']}", timeout=300) as response:
                    detail = json.load(response)
                for snap in detail.get("snapshots") or []:
                    if snap.get("observation_id") == c.get("observation_id"):
                        snapshots[str(c.get("observation_id"))] = snap
        else:
            snapshots = snapshots_by_observation_id(str(c.get("observation_id")) for c in confirmations)
        resolver = Resolver(fetch)
        written = resolver.run(confirmations, snapshots.get)
        counts = Counter(row.get("status") for row in resolver.store.all_latest())
        return {"confirmations": len(confirmations), "revisions_written": written, **counts}
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
    if sys.argv[1:2] != ["backfill"]:
        raise SystemExit("usage: python signal_outcomes.py backfill [--engine http://127.0.0.1:8000]")
    print(json.dumps(backfill(engine_url=sys.argv[3] if sys.argv[2:3] == ["--engine"] else None), indent=1))
