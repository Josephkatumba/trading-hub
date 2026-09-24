from __future__ import annotations

import hashlib
import json
import math
import uuid
import threading
from bisect import bisect_left, bisect_right, insort
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from schemas import DataQuality, SetupConfirmationEvent, SetupLifecycleEvent, SetupSnapshot
from episode_identity import identity_evidence, rank_candidates
from market_time import parse_aware_utc, utc_iso
from jsonl_index import ensure_trailing_newline, index_for, indexed_jsonl_records
from strategies import EVIDENCE_CONTAINER, REGISTRY as STRATEGIES, record_strategy_id

DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_FILE = DATA_DIR / "setup_observations.jsonl"
LIFECYCLE_FILE = DATA_DIR / "setup_lifecycle.jsonl"
CONFIRMATIONS_FILE = DATA_DIR / "setup_confirmations.jsonl"
SCHEMA_VERSION = "1.0"
_PERSISTENCE_LOCK = threading.RLock()
_SOURCE_FUTURE_TOLERANCE_SECONDS = 5.0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    result.append(value)
            except json.JSONDecodeError:
                continue
    return result


def _append(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ensure_trailing_newline(path)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")


def _state(market: dict[str, Any], previous: str | None = None) -> str:
    """Map scanner output into a durable episode lifecycle without changing it."""
    state = str(market.get("state", "WATCHING")).upper()
    confirmed = market.get("strategy_valid") is True
    target = ("CONFIRMED" if confirmed else "CONFIRMING" if state == "CONFIRMING"
             else "DEVELOPING" if state == "DEVELOPING" else "DETECTED")
    progression = {"DETECTED": 0, "DEVELOPING": 1, "CONFIRMING": 2,
                   "CONFIRMED": 3, "ACTIVE": 4}
    # Scanner states can flicker between candles. Keep episode progress monotonic.
    if previous in progression and progression[target] < progression[previous]:
        return previous
    if previous == "CONFIRMED" and target == "CONFIRMED":
        return "ACTIVE"
    return target


def _latest_lifecycle_state(setup_id: str, events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("setup_id") == setup_id:
            return str(event.get("to_state") or "") or None
    return None


def _identity_key(market: dict[str, Any]) -> str:
    # Strategy-family details can evolve while the same directional setup is
    # observed. Keep identity stable across those scanner state changes.
    parts = [str(market.get("symbol", "UNKNOWN")), str(market.get("direction") or "NONE")]
    return "|".join(parts)


def _legacy_id(row: dict[str, Any]) -> str:
    return "stp_legacy_" + hashlib.sha256(_identity_key(row).encode()).hexdigest()[:24]


# ----- observation index -------------------------------------------------
# A derived index over LOG_FILE (see jsonl_index.py). Each summary holds only the
# fields readers below need without the full row; full rows are re-read from the
# JSONL by byte offset. The k_* keys reproduce the exact matching rules of the
# former full scans (frozen in tests/legacy_observations.py for comparison).
_SUMMARY_FIELDS = ("setup_id", "observation_id", "observed_at", "timestamp", "symbol",
                   "direction", "lifecycle_state", "broker_symbol")
_PERFORMANCE_FIELDS = ("setup_id", "observation_id", "observed_at", "timestamp", "symbol",
                       "direction", "lifecycle_state")
_OBSERVATION_INDEX_SCHEMA = "observations-v3"
_LIFECYCLE_INDEX_SCHEMA = "lifecycle-v1"
_CONFIRMATION_INDEX_SCHEMA = "confirmations-v1"
_TERMINAL_STATES = frozenset({"INVALIDATED", "EXPIRED", "RESOLVED"})


def _closed_episode_fields(row: dict[str, Any], snapshot: bool) -> dict[str, Any] | None:
    """What terminal suppression reads from an episode's latest row ("ep").

    st: strategy_id (read-time mapped); fp: trendline fingerprint, present only
    when the episode has a trendline identity; px: float(reference price) or
    None. None means the row cannot be represented exactly, and _record_markets
    then uses the full-row path.
    """
    if "_terminal_state" in row:
        return None
    if snapshot:
        setup_id, identity = row.get("setup_id"), row.get("episode_identity")
        if not isinstance(setup_id, str) or not setup_id or (identity and not isinstance(identity, dict)):
            return None
        line = (identity or {}).get("trendline_identity")
        price = row.get("reference_price", row.get("price"))
    else:
        line, price = row.get("trendline_identity"), row.get("price")
    if any(value is not None and not isinstance(value, str) for value in (row.get("symbol"), row.get("direction"))):
        return None
    fields: dict[str, Any] = {"st": record_strategy_id(row)}
    if line:
        if not isinstance(line, dict) or not isinstance(line.get("fingerprint"), (str, type(None))):
            return None
        fields["fp"] = line.get("fingerprint")
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(price):
            return None
    fields["px"] = price
    return fields


def _observation_summary(row: dict[str, Any]) -> dict[str, Any]:
    record_type = row.get("record_type")
    summary: dict[str, Any] = {field: row[field] for field in _SUMMARY_FIELDS if field in row}
    summary["rt"] = record_type
    if "setup_id" in row:
        summary["k_sid"] = str(row["setup_id"])            # setup_history by setup_id
    if "observation_id" in row:
        summary["k_oid"] = str(row["observation_id"])      # setup_history by observation_id
    if not record_type:
        summary["k_legacy"] = _legacy_id(row)              # setup_history legacy fallback
    if record_type == "setup_snapshot":
        summary["k_episode"] = row.get("setup_id")         # _record_markets episode map
        if row.get("setup_id"):
            summary["k_snap"] = row["setup_id"]            # setup_episodes
        summary["k_snap_oid"] = str(row.get("observation_id"))
        summary["strategy_valid"] = (row.get("rule_evidence") or {}).get("strategy_valid") is True
        summary["tz_status"] = (row.get("time_provenance") or {}).get("timezone_normalization_status")
    elif row.get("symbol"):
        summary["k_episode"] = _legacy_id(row)
    if "k_episode" in summary:
        summary["ep"] = _closed_episode_fields(row, record_type == "setup_snapshot")
    return summary


def _observation_index():
    return index_for(LOG_FILE, _observation_summary,
                     ("k_sid", "k_oid", "k_legacy", "k_episode", "k_snap", "k_snap_oid"),
                     schema=_OBSERVATION_INDEX_SCHEMA)


def observation_index_stats() -> dict[str, Any]:
    return _observation_index().stats()


def _lifecycle_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {"sid": event.get("setup_id", ""), "to": event.get("to_state")}


def _lifecycle_index():
    return index_for(LIFECYCLE_FILE, _lifecycle_summary, (), schema=_LIFECYCLE_INDEX_SCHEMA)


def _confirmation_summary(row: dict[str, Any]) -> dict[str, Any]:
    setup_id = row.get("setup_id")
    try:
        hash(setup_id)
    except TypeError:
        return {"unhashable": True}
    return {"sid": setup_id}


def _confirmation_index():
    return index_for(CONFIRMATIONS_FILE, _confirmation_summary, ("sid", "unhashable"),
                     schema=_CONFIRMATION_INDEX_SCHEMA)


# ----- episode state for _record_markets ------------------------------------
# _record_markets needs every OPEN episode as a full row, but of a CLOSED
# episode only what terminal suppression reads. _EpisodeTable derives both from
# the observation index (latest summary per episode key, incl. "ep") and the
# lifecycle index (last to_state per setup_id), consuming only rows appended
# since the previous scan. Closed episodes are bucketed by (strategy, symbol, direction)
# and addressed by first-appearance rank, so suppression finds the same first
# match as the former in-order walk without visiting every closed episode.
# Stores holding rows the compact form cannot represent exactly use
# _FullEpisodeView, which is the former implementation.
def _episode_from_row(key: Any, row: dict[str, Any], record_type: Any) -> dict[str, Any]:
    if record_type == "setup_snapshot":
        return dict(row)
    # Deterministically adapt legacy observations without rewriting them.
    return {**row, "setup_id": key, "timeframe": "M15",
        "reference_price": row.get("price"), "setup_type": row.get("setup_family") or row.get("trendline_state"),
        "lifecycle_state": "ACTIVE" if row.get("state") in {"DEVELOPING", "CONFIRMING"} else "DETECTED",
        "episode_identity": {"trendline_identity": row.get("trendline_identity")}}


def _suppresses(episode: dict[str, Any], market: dict[str, Any], terminal_state) -> bool:
    """The terminal-suppression rule, evaluated exactly as the former walk did,
    within one strategy: another strategy's closed episode never suppresses."""
    if record_strategy_id(episode) != record_strategy_id(market):
        return False
    if episode.get("symbol") != market.get("symbol") or episode.get("direction") != market.get("direction"):
        return False
    # Terminal episodes suppress exact trendline recurrence and near-price
    # repeats; new anchors or a material price displacement are eligible.
    old_tl = (episode.get("episode_identity") or {}).get("trendline_identity")
    new_tl = identity_evidence(market).get("trendline_identity")
    exact_tl = bool(old_tl and new_tl and old_tl.get("fingerprint") == new_tl.get("fingerprint"))
    old_price = episode.get("reference_price", episode.get("price"))
    near = old_price is not None and market.get("price") is not None and abs(float(old_price)-float(market["price"])) <= max(0.00000001, float(market.get("atr") or 0) * 3)
    return terminal_state(episode) != "EXPIRED" and (exact_tl or (not old_tl and not new_tl and near))


class _ClosedBucket:
    """Closed episodes sharing (strategy, symbol, direction), addressed by first-appearance rank."""

    def __init__(self) -> None:
        self.count = 0
        self.by_fingerprint: dict[Any, list[int]] = {}  # non-EXPIRED, with trendline
        self.unlined: list[tuple[float, int]] = []     # non-EXPIRED, no trendline, priced

    def _lists(self, rank: int, fields: dict[str, Any], to_state: Any):
        if to_state == "EXPIRED":
            return
        if "fp" in fields:
            yield self.by_fingerprint.setdefault(fields["fp"], []), rank
        elif fields["px"] is not None:
            yield self.unlined, (fields["px"], rank)

    def add(self, rank: int, fields: dict[str, Any], to_state: Any) -> None:
        self.count += 1
        for target, item in self._lists(rank, fields, to_state):
            insort(target, item)

    def remove(self, rank: int, fields: dict[str, Any], to_state: Any) -> None:
        self.count -= 1
        for target, item in self._lists(rank, fields, to_state):
            target.remove(item)
        if "fp" in fields and not self.by_fingerprint.get(fields["fp"], True):
            del self.by_fingerprint[fields["fp"]]

    def first_near(self, price: float, tolerance: float) -> int | None:
        if math.isfinite(price) and math.isfinite(tolerance):
            # Widened bisect window; the exact former comparison decides below.
            margin = (abs(price) + tolerance) * 1e-9
            low = bisect_left(self.unlined, (price - tolerance - margin,))
            high = bisect_right(self.unlined, (price + tolerance + margin, math.inf))
            window = self.unlined[low:high]
        else:
            window = self.unlined
        ranks = [rank for old_price, rank in window if abs(old_price - price) <= tolerance]
        return min(ranks) if ranks else None


class _EpisodeTable:
    """Incrementally maintained episode state for one (observations, lifecycle) store."""

    def __init__(self, observation_index, lifecycle_index) -> None:
        self.observation_index = observation_index
        self.lifecycle_index = lifecycle_index
        self._clear()

    def _clear(self) -> None:
        self.cursors: tuple[Any, Any] = (None, None)
        self.rank: dict[str, int] = {}       # episode key -> first-appearance rank
        self.keys: list[str] = []            # rank -> episode key
        self.latest: dict[str, tuple[int, dict[str, Any]]] = {}  # key -> latest (position, summary)
        self.last_to: dict[Any, Any] = {}    # setup_id -> to_state of its last lifecycle event
        self.open: set[str] = set()
        self.closed: dict[str, tuple[tuple[Any, Any], int, dict[str, Any], Any]] = {}
        self.buckets: dict[tuple[Any, Any], _ClosedBucket] = {}
        self.irregular: set[str] = set()     # keys whose latest row has no exact compact form
        self.broken = False                  # a key or event only the full-row path can reproduce

    def refresh(self) -> None:
        """Apply rows appended since the last refresh. Hold both index locks."""
        observation_cursor, observation_reset, observation_rows = self.observation_index.delta(self.cursors[0])
        lifecycle_cursor, lifecycle_reset, lifecycle_rows = self.lifecycle_index.delta(self.cursors[1])
        if observation_reset or lifecycle_reset:
            self._clear()
            observation_cursor, _, observation_rows = self.observation_index.delta(None)
            lifecycle_cursor, _, lifecycle_rows = self.lifecycle_index.delta(None)
        self.cursors = (observation_cursor, lifecycle_cursor)
        dirty: set[str] = set()
        start = observation_cursor[1] - len(observation_rows)
        for offset, summary in enumerate(observation_rows):
            if "k_episode" not in summary:
                continue
            key = summary["k_episode"]
            if not isinstance(key, str):
                self.broken = True
                continue
            if key not in self.rank:
                self.rank[key] = len(self.keys)
                self.keys.append(key)
            self.latest[key] = (start + offset, summary)
            dirty.add(key)
        for summary in lifecycle_rows:
            setup_id, to_state = summary.get("sid"), summary.get("to")
            try:
                hash(setup_id), hash(to_state)
            except TypeError:
                self.broken = True
                continue
            self.last_to[setup_id] = to_state
            if setup_id in self.latest:
                dirty.add(setup_id)
        for key in dirty:
            self._place(key)

    def _place(self, key: str) -> None:
        self.open.discard(key)
        if key in self.closed:
            bucket_key, rank, fields, to_state = self.closed.pop(key)
            self.buckets[bucket_key].remove(rank, fields, to_state)
        summary = self.latest[key][1]
        fields = summary.get("ep")
        if fields is None:
            self.irregular.add(key)
            return
        self.irregular.discard(key)
        to_state = self.last_to.get(key)
        if to_state not in _TERMINAL_STATES:
            self.open.add(key)
            return
        bucket_key = (fields["st"], summary.get("symbol"), summary.get("direction"))
        rank = self.rank[key]
        self.buckets.setdefault(bucket_key, _ClosedBucket()).add(rank, fields, to_state)
        self.closed[key] = (bucket_key, rank, fields, to_state)


class _IndexedEpisodeView:
    """Open episodes as full rows; closed episodes answered from the table."""

    def __init__(self, table: _EpisodeTable) -> None:
        self.table = table
        keys = sorted(table.open, key=table.rank.__getitem__)
        rows = table.observation_index.load(table.latest[key][0] for key in keys)
        self.open_episodes = [_episode_from_row(key, row, table.latest[key][1]["rt"])
                              for key, row in zip(keys, rows)]

    def latest_state(self, setup_id: str) -> str | None:
        if setup_id not in self.table.last_to:
            return None
        return str(self.table.last_to[setup_id] or "") or None

    def persisted_match(self, market: dict[str, Any]) -> tuple[Any, Any] | None:
        try:
            bucket = self.table.buckets.get((record_strategy_id(market), market.get("symbol"), market.get("direction")))
        except TypeError:
            return None  # unhashable market fields never equal a stored symbol/direction
        if bucket is None or not bucket.count:
            return None
        new_tl = identity_evidence(market).get("trendline_identity")
        match = None
        if new_tl:
            ranks = bucket.by_fingerprint.get(new_tl.get("fingerprint"))
            match = ranks[0] if ranks else None
        elif bucket.unlined and market.get("price") is not None:
            match = bucket.first_near(float(market["price"]), max(0.00000001, float(market.get("atr") or 0) * 3))
        if match is None:
            return None
        key = self.table.keys[match]
        return key, self.table.last_to[key]


class _FullEpisodeView:
    """The former implementation: latest full row of every episode + full lifecycle read."""

    def __init__(self) -> None:
        self.events = _read_jsonl(LIFECYCLE_FILE)
        episodes: dict[str, dict[str, Any]] = {}
        # Only the latest row per episode key matters (later rows overwrote earlier
        # ones in the former full scan); dict order stays first appearance.
        index = _observation_index()
        with index.lock:
            groups = index.groups("k_episode")
            keys = list(groups)
            latest_positions = [groups[key][-1] for key in keys]
            kinds = [index.summary(position)["rt"] for position in latest_positions]
            latest_rows = index.load(latest_positions)
        for key, row, record_type in zip(keys, latest_rows, kinds):
            if record_type == "setup_snapshot":
                episodes[row["setup_id"]] = dict(row)
            else:
                episodes[key] = _episode_from_row(key, row, record_type)
        self.event_state: dict[str, dict[str, Any]] = {}
        for event in self.events:
            self.event_state[event.get("setup_id", "")] = event
        self.open_episodes = [row for sid, row in episodes.items()
                              if self.event_state.get(sid, {}).get("to_state") not in _TERMINAL_STATES]
        self.terminal_episodes = [row for sid, row in episodes.items()
                                  if self.event_state.get(sid, {}).get("to_state") in _TERMINAL_STATES]

    def latest_state(self, setup_id: str) -> str | None:
        return _latest_lifecycle_state(setup_id, self.events)

    def _terminal_state(self, episode: dict[str, Any]) -> Any:
        return episode.get("_terminal_state") or self.event_state.get(episode["setup_id"], {}).get("to_state")

    def persisted_match(self, market: dict[str, Any]) -> tuple[Any, Any] | None:
        for episode in self.terminal_episodes:
            if _suppresses(episode, market, self._terminal_state):
                return episode["setup_id"], (episode.get("_terminal_state") or
                    self.event_state.get(episode["setup_id"], {}).get("to_state", "EXPIRED"))
        return None


_EPISODE_TABLES: dict[tuple[Any, Any], _EpisodeTable] = {}


def _episode_view():
    observation_index, lifecycle_index = _observation_index(), _lifecycle_index()
    table = _EPISODE_TABLES.get((observation_index, lifecycle_index))
    if table is None:
        table = _EPISODE_TABLES[(observation_index, lifecycle_index)] = _EpisodeTable(observation_index, lifecycle_index)
    with observation_index.lock, lifecycle_index.lock:
        table.refresh()
        if table.broken or table.irregular:
            return _FullEpisodeView()
        return _IndexedEpisodeView(table)


def _uid(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex


def _quality(market: dict[str, Any], observed_at: str) -> DataQuality:
    source_ts = market.get("source_timestamp")
    flags = list(market.get("data_quality_flags") or [])
    notes: list[str] = []
    provenance = market.get("time_provenance") or {}
    timestamp_quality = str(provenance.get("timezone_normalization_status") or
                            provenance.get("normalization_status") or "UNVERIFIED")
    age = market.get("tick_age_seconds")
    candle_age = market.get("candle_age_seconds")
    latency = None
    received = market.get("backend_received_at")
    if received:
        observed_dt = parse_aware_utc(observed_at)
        received_dt = parse_aware_utc(received)
        if observed_dt is not None and received_dt is not None:
            latency = max(0.0, (observed_dt - received_dt).total_seconds())
        else:
            flags.append("INVALID_BACKEND_RECEIVED_TIME")
    if timestamp_quality != "VERIFIED":
        flags.append("SOURCE_TIME_BASIS_UNVERIFIED" if timestamp_quality == "UNVERIFIED" else "SOURCE_TIME_INVALID")
        notes.append("MT5 source clock basis is not verified; feed freshness and cross-domain candle age are unavailable.")
    if candle_age is not None and float(candle_age) < -_SOURCE_FUTURE_TOLERANCE_SECONDS:
        flags.append("BAR_OPEN_AFTER_TICK")
        notes.append("Candle open is later than the quote tick in the MT5 source clock domain.")
    if timestamp_quality == "VERIFIED" and age is not None and float(age) < -_SOURCE_FUTURE_TOLERANCE_SECONDS:
        flags.append("FUTURE_SOURCE_TIMESTAMP")
        notes.append("Verified tick time is ahead of backend observation time; feed freshness is untrusted.")
    if timestamp_quality == "VERIFIED" and source_ts:
        source = parse_aware_utc(source_ts)
        observed = parse_aware_utc(observed_at)
        if source is not None and observed is not None:
            signed_age = (observed - source).total_seconds()
            if signed_age < -_SOURCE_FUTURE_TOLERANCE_SECONDS:
                flags.append("FUTURE_SOURCE_TIMESTAMP")
                notes.append("Verified source time is ahead of backend observation time.")
                age = signed_age
            elif age is None:
                age = max(0.0, signed_age)
        else:
            flags.append("INVALID_SOURCE_TIMESTAMP")
    return DataQuality(status="DEGRADED" if flags else "OK", flags=flags,
        source=str(market.get("source") or "MT5"), source_timestamp=source_ts,
        observed_at=observed_at, source_age_seconds=age,
        timeframe=str(market.get("timeframe") or "M15"), expected_bars=300,
        received_bars=market.get("received_bars"), missing_intervals=None,
        notes=notes, candle_age_seconds=candle_age, tick_age_seconds=age,
        observation_latency_seconds=latency, timestamp_quality=timestamp_quality)


def _strategy_version(strategy_id: str, market: dict[str, Any]) -> str:
    """The registered strategy's version; an unregistered id keeps what the market reports."""
    try:
        return STRATEGIES.get(strategy_id).version
    except KeyError:
        return str(market.get("strategy_version") or "unregistered")


def _snapshot(market: dict[str, Any], setup_id: str, state: str, now: str) -> SetupSnapshot:
    observation_id = _uid("obs")
    strategy_id = record_strategy_id(market)
    source_ts = market.get("source_timestamp")
    features = {key: market.get(key) for key in (
        "price", "bid", "ask", "spread", "change_pct", "rsi", "ema20", "ema50",
        "atr", "higher_timeframe_bias", "market_bias", "momentum", "structure",
        "price_action", "price_action_state", "trendline", "trendline_state",
        "trendline_line", "nearest_level", "nearest_level_type", "nearest_level_atr",
        "spread_atr", "crt_context", "crt_state") if key in market}
    features.update({key: market.get(key) for key in ("rr", "risk_distance", "reward_distance") if key in market})
    rule_evidence = {key: market.get(key) for key in (
        "scanner_state", "trendline_gate", "confirmation_alignment", "strategy_valid", "reason", "trigger",
        "invalidation_hint", "stage", "action") if key in market}
    rule_evidence["scanner_state"] = market.get("state")
    time_provenance = dict(market.get("time_provenance") or {})
    time_provenance["backend_received_at"] = market.get("backend_received_at")
    time_provenance["backend_observation_time"] = now
    time_provenance["observation_time"] = now
    return SetupSnapshot(record_type="setup_snapshot", schema_version=SCHEMA_VERSION,
        setup_id=setup_id, observation_id=observation_id, observed_at=now,
        source_timestamp=source_ts, symbol=str(market.get("symbol", "UNKNOWN")),
        broker_symbol=market.get("broker_symbol"), timeframe=str(market.get("timeframe") or "M15"),
        higher_timeframes=list(market.get("higher_timeframes") or ["H1"]),
        direction=market.get("direction"), strategy_id=strategy_id,
        strategy_version=_strategy_version(strategy_id, market),
        setup_type=market.get("setup_family") or market.get("trendline_state") or "GENERAL", lifecycle_state=state,
        reference_price=market.get("price"), proposed_entry=market.get("entry"),
        proposed_stop_loss=market.get("stop_loss"), proposed_take_profit=market.get("take_profit"),
        features=features, rule_evidence=rule_evidence,
        strategy_evidence=dict(market.get(EVIDENCE_CONTAINER) or {}), score=market.get("score"),
        score_breakdown=dict(market.get("score_breakdown") or {}),
        session={key: market.get(key) for key in ("session", "london_high", "london_low", "london_complete", "session_alignment", "london_date", "new_york_time") if key in market},
        data_freshness={"candle_age_seconds": _quality(market, now).get("candle_age_seconds"),
            "tick_age_seconds": _quality(market, now).get("tick_age_seconds"),
            "observation_latency_seconds": _quality(market, now).get("observation_latency_seconds"),
            "timestamp_quality": _quality(market, now).get("timestamp_quality")},
        data_quality=_quality(market, now),
        episode_identity={**identity_evidence(market), "strategy_id": strategy_id},
        invalidation_price=market.get("invalidation_hint"), atr=market.get("atr"),
        time_provenance=time_provenance)


def _record_markets(markets: list[dict[str, Any]]) -> int:
    """Append immutable observations and match them to persisted open episodes."""
    view = _episode_view()
    open_episodes = view.open_episodes
    # Episodes closed during this call; the former walk visited them after the persisted ones.
    closed_now: list[dict[str, Any]] = []

    now_dt = datetime.now(timezone.utc)
    now = utc_iso(now_dt)
    snapshots: list[dict[str, Any]] = []
    lifecycle: list[dict[str, Any]] = []
    max_gap = 86400.0
    try:
        import os
        max_gap = max(60.0, float(os.getenv("TRADING_HUB_EPISODE_MAX_GAP_SECONDS", max_gap)))
    except (TypeError, ValueError):
        pass
    # Close episodes that went stale even when MT5 no longer returns that symbol.
    for episode in list(open_episodes):
        try:
            last_seen = parse_aware_utc(episode.get("observed_at"))
            if last_seen is None:
                continue
        except (TypeError, ValueError):
            continue
        if (now_dt - last_seen).total_seconds() <= max_gap:
            continue
        sid = episode["setup_id"]
        from_state = view.latest_state(sid) or str(episode.get("lifecycle_state") or "DETECTED")
        lifecycle.append(SetupLifecycleEvent(record_type="setup_lifecycle_event", schema_version=SCHEMA_VERSION,
            event_id=_uid("evt"), setup_id=sid, occurred_at=now, from_state=from_state,
            to_state="EXPIRED", reason_code="INACTIVITY_TIMEOUT", reason="No matching scanner observation within the episode time limit.",
            triggering_observation_id=None, metadata={"max_gap_seconds": max_gap}))
        open_episodes.remove(episode)
        episode["_terminal_state"] = "EXPIRED"
        closed_now.append(episode)
    for market in markets:
        # Episodes are scoped by strategy: another strategy's episode on the same
        # symbol is never a candidate, so it cannot be continued, invalidated or expired.
        candidates = [episode for episode in open_episodes
                      if record_strategy_id(episode) == record_strategy_id(market)
                      and episode.get("symbol") == market.get("symbol")
                      and str(episode.get("timeframe") or "M15") == str(market.get("timeframe") or "M15")]
        previous, evaluated = rank_candidates(market, candidates, now_dt)
        # Close episodes explicitly when their continuity breaks or they expire.
        for episode, decision, reason, _ in evaluated:
            if decision not in {"INVALIDATE", "EXPIRE"}:
                continue
            from_state = str(episode.get("lifecycle_state") or "DETECTED")
            to_state = "INVALIDATED" if decision == "INVALIDATE" else "EXPIRED"
            lifecycle.append(SetupLifecycleEvent(record_type="setup_lifecycle_event", schema_version=SCHEMA_VERSION,
                event_id=_uid("evt"), setup_id=episode["setup_id"], occurred_at=now,
                from_state=from_state, to_state=to_state, reason_code=reason or decision,
                reason=reason, triggering_observation_id=None, metadata={"matcher_version": "episode-match-v1"}))
            episode["_terminal_state"] = to_state
            open_episodes = [item for item in open_episodes if item.get("setup_id") != episode.get("setup_id")]
            closed_now.append(episode)

        if str(market.get("state", "")).upper() not in {"WATCHING", "DEVELOPING", "CONFIRMING"}:
            continue

        # Do not immediately recreate a just-terminal episode on the same unchanged
        # trendline/price evidence. A materially new trendline can start a new one.
        match = view.persisted_match(market)
        if match is None:
            match = next(((episode["setup_id"], episode["_terminal_state"]) for episode in closed_now
                          if _suppresses(episode, market, lambda item: item["_terminal_state"])), None)
        if match is not None:
            market.update({"setup_id": match[0], "lifecycle_state": match[1], "episode_suppressed": True})
            continue

        setup_id = previous["setup_id"] if previous else _uid("stp")
        prior_state = (view.latest_state(setup_id) if previous else None) or (str(previous.get("lifecycle_state")) if previous else None)
        from_state = prior_state
        to_state = _state(market, prior_state)
        snapshot = _snapshot(market, setup_id, to_state, now)
        snapshots.append(dict(snapshot))
        if from_state != to_state:
            lifecycle.append(SetupLifecycleEvent(record_type="setup_lifecycle_event", schema_version=SCHEMA_VERSION,
                event_id=_uid("evt"), setup_id=setup_id, occurred_at=now, from_state=from_state,
                to_state=to_state, reason_code="FIRST_DETECTION" if from_state is None else "SCANNER_STATE_CHANGED",
                reason=str(market.get("reason") or "") or None, triggering_observation_id=snapshot["observation_id"], metadata={}))
        # Keep the legacy top-level market fields available to existing clients.
        market.update({"setup_id": setup_id, "observation_id": snapshot["observation_id"],
                       "lifecycle_state": to_state, "observed_at": now,
            "data_quality": snapshot["data_quality"], "data_freshness": snapshot["data_freshness"],
            "source": "MT5", "episode_identity": snapshot["episode_identity"],
            "time_provenance": snapshot["time_provenance"],
            "invalidation_price": snapshot["invalidation_price"]})
    _append(LOG_FILE, snapshots)
    _append(LIFECYCLE_FILE, [dict(event) for event in lifecycle])
    _record_confirmation_events(snapshots)
    return len(snapshots)


def _record_confirmation_events(current_snapshots: list[dict[str, Any]]) -> int:
    index = _confirmation_index()
    with index.lock:
        if index.lookup("unhashable", True):
            seen: Any = {row.get("setup_id") for row in _read_jsonl(CONFIRMATIONS_FILE)}
        else:
            # setup_id -> rows: the same membership semantics as the former set of
            # every confirmed setup_id. Only this (serialized) writer appends to it.
            seen = index.maps["sid"]
    candidates: dict[str, dict[str, Any]] = {}
    # Backfill confirmed historical observations once, without editing their lines.
    if not CONFIRMATIONS_FILE.exists() or CONFIRMATIONS_FILE.stat().st_size == 0:
        for row in _read_jsonl(LOG_FILE):
            if row.get("record_type") == "setup_snapshot":
                sid = row.get("setup_id")
                valid = (row.get("rule_evidence") or {}).get("strategy_valid") is True
            elif row.get("symbol"):
                sid = "stp_legacy_" + hashlib.sha256(_identity_key(row).encode()).hexdigest()[:24]
                valid = row.get("strategy_valid") is True
            else:
                continue
            if not valid or not sid:
                continue
            old = candidates.get(sid)
            if old is None or str(row.get("observed_at", "")) < str(old.get("observed_at", "")):
                candidates[sid] = row
    for row in current_snapshots:
        if (row.get("rule_evidence") or {}).get("strategy_valid") is True and row.get("setup_id") not in seen:
            old = candidates.get(row["setup_id"])
            if old is None or str(row.get("observed_at", "")) < str(old.get("observed_at", "")):
                candidates[row["setup_id"]] = row

    append = []
    for setup_id, snapshot in candidates.items():
        if setup_id in seen:
            continue
        confirmed_at = parse_aware_utc(snapshot.get("observed_at")) or datetime.now(timezone.utc)
        append.append(SetupConfirmationEvent(record_type="setup_confirmation", schema_version=SCHEMA_VERSION,
            confirmation_event_id=_uid("cnf"), setup_id=setup_id,
            confirmed_at=utc_iso(confirmed_at),
            observation_id=str(snapshot.get("observation_id") or "legacy"),
            strategy_id=record_strategy_id(snapshot),
            strategy_version=str(snapshot.get("strategy_version") or "trendline-first-v3"),
            symbol=str(snapshot.get("symbol") or "UNKNOWN"), direction=snapshot.get("direction"),
            setup_type=snapshot.get("setup_type") or snapshot.get("setup_family"),
            timeframe=str(snapshot.get("timeframe") or "M15"),
            score=snapshot.get("score"), rule_evidence=dict(snapshot.get("rule_evidence") or {}),
            score_breakdown=dict(snapshot.get("score_breakdown") or {})))
    _append(CONFIRMATIONS_FILE, [dict(row) for row in append])
    return len(append)


def confirmation_events(setup_id: str | None = None) -> list[dict[str, Any]]:
    rows = _read_jsonl(CONFIRMATIONS_FILE)
    return [row for row in rows if setup_id is None or row.get("setup_id") == setup_id]


def all_observations() -> list[dict[str, Any]]:
    """Read raw snapshots and legacy rows without modifying the append-only log."""
    return _read_jsonl(LOG_FILE)


def record_markets(markets: list[dict[str, Any]]) -> int:
    """Serialize identity selection and append operations within this engine process."""
    with _PERSISTENCE_LOCK:
        return _record_markets(markets)


def recent_observations(limit: int = 100) -> list[dict[str, Any]]:
    count = max(1, min(limit, 1000))
    if not LOG_FILE.exists():
        return []
    chunk_size = 1024 * 1024
    chunks: list[bytes] = []
    position = LOG_FILE.stat().st_size
    newlines = 0
    with LOG_FILE.open("rb") as handle:
        while position > 0 and newlines <= count:
            start = max(0, position - chunk_size)
            handle.seek(start)
            chunk = handle.read(position - start)
            chunks.append(chunk)
            newlines += chunk.count(b"\n")
            position = start
    data = b"".join(reversed(chunks))
    rows = []
    for line in data.splitlines()[-count:]:
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return list(reversed(rows))


def setup_history(setup_id: str) -> list[dict[str, Any]]:
    if setup_id is None:
        return []
    index = _observation_index()
    with index.lock:
        rows = index.load(index.lookup("k_sid", str(setup_id)) + index.lookup("k_oid", str(setup_id)))
    if rows:
        rows.sort(key=lambda row: str(row.get("observed_at") or row.get("timestamp") or ""))
        return rows
    # Preserve lookup compatibility for pre-episode rows, whose stable legacy
    # identity is derived from symbol/direction rather than stored as setup_id.
    with index.lock:
        return index.load(index.lookup("k_legacy", setup_id))


def snapshots_by_observation_id(observation_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """{str(observation_id): latest setup_snapshot with that id}, for the given ids only.

    Same mapping as {str(row.get("observation_id")): row for every setup_snapshot}
    (last occurrence wins), restricted to the ids a caller will look up.
    """
    index = _observation_index()
    with index.lock:
        wanted: list[tuple[str, int]] = []
        for observation_id in dict.fromkeys(str(value) for value in observation_ids):
            positions = index.lookup("k_snap_oid", observation_id)
            if positions:
                wanted.append((observation_id, positions[-1]))
        rows = index.load(position for _, position in wanted)   # one file read for all
    return {observation_id: row for (observation_id, _), row in zip(wanted, rows)}


def outcome_watch_snapshots(claimed_observation_ids: set[str], symbols_with_bars: set[str],
                            present_keys: set[tuple[Any, ...]], horizons: Iterable[str],
                            label_definition: str = "target-invalidation-first-v1") -> list[dict[str, Any]]:
    """WATCH snapshots that outcomes.resolve_due_market_outcomes could still label.

    Mirrors that function's own skip rules (first occurrence per observation_id,
    after the confirmation snapshots in `claimed_observation_ids`; VERIFIED time;
    a symbol with bars; at least one missing horizon), so dropping the other rows
    here cannot change its output. It still re-checks everything itself.
    """
    horizons = tuple(horizons)
    index = _observation_index()
    visited = set(claimed_observation_ids)
    selected: list[int] = []
    with index.lock:
        for position, summary in enumerate(index.summaries()):
            if summary["rt"] != "setup_snapshot" or summary.get("strategy_valid"):
                continue
            observation_id = str(summary.get("observation_id") or "")
            if not observation_id or observation_id in visited:
                continue
            visited.add(observation_id)
            if summary.get("tz_status") != "VERIFIED":
                continue
            if str(summary.get("symbol") or "") not in symbols_with_bars:
                continue
            if all((summary.get("setup_id"), summary.get("observation_id"), horizon, label_definition)
                   in present_keys for horizon in horizons):
                continue
            selected.append(position)
        return index.load(selected)


def performance_observations() -> list[dict[str, Any]]:
    """The fields performance.performance_report reads from each observation row."""
    return [{field: summary[field] for field in _PERFORMANCE_FIELDS if field in summary}
            for summary in _observation_index().summaries()]


def latest_broker_symbols() -> dict[str, str]:
    """symbol -> broker symbol from the most recent row carrying both."""
    mapping: dict[str, str] = {}
    for summary in reversed(_observation_index().summaries()):
        if summary.get("symbol") and summary.get("broker_symbol"):
            mapping.setdefault(str(summary["symbol"]), str(summary["broker_symbol"]))
    return mapping


def lifecycle_events(setup_id: str | None = None) -> list[dict[str, Any]]:
    if setup_id is not None:
        return indexed_jsonl_records(LIFECYCLE_FILE, "setup_id", setup_id)
    return _read_jsonl(LIFECYCLE_FILE)


def setup_episodes(bucket: str = "current", limit: int = 100) -> list[dict[str, Any]]:
    """Return a bounded episode view built from append-only snapshots and events."""
    confirmations = {row.get("setup_id"): row for row in _read_jsonl(CONFIRMATIONS_FILE)}
    events = _read_jsonl(LIFECYCLE_FILE)
    # First and latest snapshot per setup, in first-appearance order.
    index = _observation_index()
    with index.lock:
        groups = index.groups("k_snap")
        sids = list(groups)
        first_observed = {sid: index.summary(groups[sid][0]).get("observed_at") for sid in sids}
        latest = dict(zip(sids, index.load(groups[sid][-1] for sid in sids)))
    event_map: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        event_map.setdefault(str(event.get("setup_id")), []).append(event)
    now = datetime.now(timezone.utc)
    output = []
    for sid, snapshot in latest.items():
        timeline = event_map.get(sid, [])
        state = str(timeline[-1].get("to_state")) if timeline else str(snapshot.get("lifecycle_state") or "DETECTED")
        confirmation = confirmations.get(sid)
        if bucket == "current" and state in {"INVALIDATED", "EXPIRED", "RESOLVED"}:
            continue
        if bucket == "confirmed" and not confirmation:
            continue
        if bucket == "closed" and state not in {"INVALIDATED", "EXPIRED", "RESOLVED"}:
            continue
        if bucket == "all":
            row_bucket = ("closed" if state in {"INVALIDATED", "EXPIRED", "RESOLVED"}
                          else "confirmed" if confirmation else "current")
        else:
            row_bucket = bucket
        detected = first_observed[sid]
        try:
            started = parse_aware_utc(detected)
            ended = (parse_aware_utc(timeline[-1].get("occurred_at"))
                     if state in {"INVALIDATED", "EXPIRED", "RESOLVED"} and timeline else now)
            duration = (max(0, int((ended - started).total_seconds()))
                        if started is not None and ended is not None else None)
        except (TypeError, ValueError):
            duration = None
        output.append({**snapshot, "strategy_id": record_strategy_id(snapshot),
            "lifecycle_state": state, "detected_at": detected,
            "duration_seconds": duration, "confirmation": confirmation,
            "confirmation_time": confirmation.get("confirmed_at") if confirmation else None,
            "closed_event": timeline[-1] if state in {"INVALIDATED", "EXPIRED", "RESOLVED"} and timeline else None,
            "bucket": row_bucket,
            "lifecycle_events": timeline})
    def recency(row: dict[str, Any]) -> str:
        if bucket == "closed":
            return str((row.get("closed_event") or {}).get("occurred_at") or row.get("observed_at") or "")
        if bucket == "confirmed":
            return str(row.get("confirmation_time") or row.get("observed_at") or "")
        return str(row.get("observed_at") or "")
    output.sort(key=recency, reverse=True)
    bounded = max(1, min(int(limit), 500))
    if bucket == "all":
        return [row for name in ("current", "confirmed", "closed")
                for row in [item for item in output if item.get("bucket") == name][:bounded]]
    return output[:bounded]


def record_lifecycle_transition(setup_id: str, to_state: str, reason_code: str,
                                reason: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    allowed = {"DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE", "INVALIDATED", "EXPIRED", "RESOLVED"}
    terminal = {"INVALIDATED", "EXPIRED", "RESOLVED"}
    history = setup_history(setup_id)
    if not history:
        raise ValueError("Unknown setup_id")
    events = lifecycle_events(setup_id)
    current = events[-1]["to_state"] if events else str(history[-1].get("lifecycle_state") or _state(history[-1]))
    if to_state not in allowed:
        raise ValueError("Unsupported lifecycle state")
    transitions = {
        "DETECTED": {"DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE", *terminal},
        "DEVELOPING": {"CONFIRMING", "CONFIRMED", "ACTIVE", *terminal},
        "CONFIRMING": {"CONFIRMED", "ACTIVE", *terminal},
        "CONFIRMED": {"ACTIVE", *terminal}, "ACTIVE": set(terminal),
    }
    if to_state not in transitions.get(current, set()):
        raise ValueError(f"Invalid lifecycle transition: {current} -> {to_state}")
    event = SetupLifecycleEvent(record_type="setup_lifecycle_event", schema_version=SCHEMA_VERSION,
        event_id=_uid("evt"), setup_id=setup_id, occurred_at=utc_iso(datetime.now(timezone.utc)),
        from_state=current, to_state=to_state, reason_code=reason_code,
        reason=reason, triggering_observation_id=history[-1].get("observation_id"),
        metadata=metadata or {})
    _append(LIFECYCLE_FILE, [dict(event)])
    return dict(event)
