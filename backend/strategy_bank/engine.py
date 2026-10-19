"""Strategy Bank confirmation engine, opportunity merging, signal store and statistics.

Gates (a strategy's decision becomes a signal only if all pass; rejections are counted, not sent):
  completed candle   decide() saw closed bars only (enforced by the callers: the forming bar is dropped)
  fresh data         the confirming bar closed within 2 bar-lengths of now; quote tick age <= 300 s
  entry drift        executable entry (ask for BUY, bid for SELL) within 0.5 ATR of the confirming close
  valid levels       stop on the loss side, 0.2-5 ATR from the entry; target on the profit side
  execution cost     spread <= 25% of the risk
  reward/risk        executable reward/risk >= the strategy's minimum (spec min_rr)
  duplicate          no new signal from the same strategy and symbol while its previous one is open
Opportunities: signals on the same symbol and direction within OPPORTUNITY_WINDOW of an open
opportunity (bank or production confirmation) are merged into it; every confirming strategy keeps
its own signal record and statistics, but only the first one may be alerted.
R multiples are HYPOTHETICAL (signal outcomes); executed-trade results come only from the journal.
"""
from __future__ import annotations

import json
import math
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from storage_config import data_directory
from strategy_bank import rules

MAX_QUOTE_AGE = 300.0
MAX_ENTRY_DRIFT_ATR = 0.5
MAX_SPREAD_RISK = 0.25
OPPORTUNITY_WINDOW = 4 * 3600.0
PRODUCTION_WINDOW = 3600.0
FINAL = ("TARGET_HIT", "STOP_HIT", "AMBIGUOUS", "NO_HIT", "UNAVAILABLE", "TIME_EXIT")


def bank_dir() -> Path:
    return data_directory() / "strategy_bank"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


# ----- contradictory evidence (objective) ------------------------------------------------------------

def contradictions(ctx: rules.Ctx, tf: str, i: int, direction: str) -> list[str]:
    """Recorded market conditions that argue against the signal, from closed bars only."""
    long = direction == "LONG"
    notes = []
    close_t = ctx.close_utc(tf, i)
    if "H4" in ctx.a:
        j = ctx.last_closed("H4", close_t)
        if j >= 200:
            e50, e200 = ctx.get("H4", "ema", 50)[j], ctx.get("H4", "ema", 200)[j]
            if (e50 < e200) if long else (e50 > e200):
                notes.append(f"the H4 trend is {'down' if long else 'up'} (EMA50 {'below' if long else 'above'} EMA200)")
    rsi = ctx.get(tf, "rsi")[i]
    if rsi == rsi and ((long and rsi >= 70) or (not long and rsi <= 30)):
        notes.append(f"RSI(14) is {'overbought' if long else 'oversold'} at {rsi:.0f}")
    atr = ctx.get(tf, "atr")[i]
    hi, lo = ctx.get(tf, "swings")
    c = ctx.a[tf]["close"][i]
    level = hi[i] if long else lo[i]
    if atr == atr and level == level and 0 <= ((level - c) if long else (c - level)) <= 0.5 * atr:
        notes.append(f"a recent swing {'high' if long else 'low'} lies within 0.5 ATR")
    line, sig = ctx.get(tf, "macd")
    if (line[i] < sig[i]) if long else (line[i] > sig[i]):
        notes.append(f"MACD is below its signal line" if long else "MACD is above its signal line")
    return notes


# ----- gates -----------------------------------------------------------------------------------------

def confirm(spec: dict[str, Any], d: rules.Decision, ctx: rules.Ctx, i: int, quote: dict[str, Any], now: float,
            check_freshness: bool = True) -> tuple[dict[str, Any] | None, str]:
    """(signal, "") when every gate passes, else (None, reason). `quote`: bid, ask, tick_age_seconds."""
    tf = spec["timeframe"]
    close_t = ctx.close_utc(tf, i)
    tf_s = rules.TF_SECONDS[tf]
    if check_freshness:
        if now - close_t > 2 * tf_s:
            return None, "stale bar"
        age = quote.get("tick_age_seconds")
        if age is None or not (age <= MAX_QUOTE_AGE):
            return None, "stale or unverified quote"
    atr = float(ctx.get(tf, "atr")[i])
    bid, ask = quote.get("bid"), quote.get("ask")
    if not (atr == atr and atr > 0 and bid and ask and ask >= bid):
        return None, "no ATR or quote"
    long = d.direction == "LONG"
    entry = float(ask if long else bid)
    close = float(ctx.a[tf]["close"][i])
    if abs(entry - close) > MAX_ENTRY_DRIFT_ATR * atr:
        return None, "entry moved more than 0.5 ATR from the confirming close"
    stop = d.stop if d.stop is not None else (entry - d.stop_atr * atr if long else entry + d.stop_atr * atr)
    if stop is None or not math.isfinite(stop):
        return None, "invalid stop"
    risk = (entry - stop) if long else (stop - entry)
    if not (0.2 * atr <= risk <= 5 * atr):
        return None, "stop distance outside 0.2-5 ATR"
    target = d.target if d.target is not None else (entry + d.target_r * risk if long else entry - d.target_r * risk)
    reward = (target - entry) if long else (entry - target)
    if not (reward > 0 and math.isfinite(target)):
        return None, "target not on the profit side"
    spread = float(ask - bid)
    if spread > MAX_SPREAD_RISK * risk:
        return None, "spread above 25% of the risk"
    rr = reward / risk
    if spec["min_rr"] is not None and rr < spec["min_rr"]:
        return None, f"reward/risk {rr:.2f} below the {spec['min_rr']} minimum"
    signal = {"record_type": "bank_signal", "signal_id": "bank_" + uuid.uuid4().hex, "strategy_key": spec["key"],
              "strategy_name": spec["name"], "strategy_number": spec.get("n"), "status": spec["status"],
              "symbol": ctx.symbol, "direction": d.direction, "timeframe": tf, "confirmed_at": _iso(close_t),
              "detected_at": _iso(now), "entry": entry, "stop_loss": float(stop), "take_profit": float(target),
              "risk": risk, "rr": round(rr, 3), "spread": spread, "atr": atr, "confirming_close": close,
              "executable": True, "execution_basis": quote.get("basis", "live quote at confirmation"),
              "time_exit_at": _iso(close_t + d.max_bars * 900) if d.max_bars else None,
              "explanation": d.explanation, "contradictions": contradictions(ctx, tf, i, d.direction),
              "evidence": {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in d.evidence.items()},
              "r_basis": "hypothetical (signal outcome, not an executed trade)"}
    return signal, ""


# ----- store -----------------------------------------------------------------------------------------

class BankStore:
    """Append-only JSONL records under <data dir>/strategy_bank; latest row per id wins."""

    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder or bank_dir()
        self._lock = threading.Lock()
        self.signals = self._load("signals.jsonl", "signal_id")
        self.opportunities = self._load("opportunities.jsonl", "opportunity_id")
        self.rejections = defaultdict(lambda: defaultdict(int))
        self.evaluated: set[tuple[str, str, str]] = {(s["strategy_key"], s["symbol"], s["confirmed_at"]) for s in self.signals.values()}

    def _load(self, name: str, key: str) -> dict[str, dict[str, Any]]:
        path = self.folder / name
        out: dict[str, dict[str, Any]] = {}
        if path.exists():
            with path.open("rb") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(row, dict) and row.get(key):
                        out[row[key]] = row
        return out

    def _append(self, name: str, row: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / name).open("ab") as handle:
            handle.write((json.dumps(row, separators=(",", ":"), default=str) + "\n").encode("utf-8"))

    def put_signal(self, row: dict[str, Any]) -> None:
        with self._lock:
            self.signals[row["signal_id"]] = row
            self._append("signals.jsonl", row)

    def put_opportunity(self, row: dict[str, Any]) -> None:
        with self._lock:
            row = {**row, "updated_at": datetime.now(timezone.utc).isoformat()}
            self.opportunities[row["opportunity_id"]] = row
            self._append("opportunities.jsonl", row)

    def open_signal(self, key: str, symbol: str) -> dict[str, Any] | None:
        for s in self.signals.values():
            if s["strategy_key"] == key and s["symbol"] == symbol and s.get("outcome_status") not in FINAL:
                return s
        return None


# ----- the engine ------------------------------------------------------------------------------------

class Bank:
    def __init__(self, store: BankStore | None = None,
                 production_confirmations: Callable[[], list[dict[str, Any]]] | None = None) -> None:
        self.store = store or BankStore()
        self.production_confirmations = production_confirmations or (lambda: [])

    def scan(self, ctx: rules.Ctx, quote: dict[str, Any], now: float, check_freshness: bool = True,
             at: dict[str, int] | None = None) -> list[dict[str, Any]]:
        """Run every scanned strategy for one symbol on its latest closed bar; returns new signals."""
        new = []
        for spec in rules.scanned():
            if ctx.symbol not in spec["instruments"]:
                continue
            tf = spec["timeframe"]
            if tf not in ctx.a:
                continue
            i = (at or {}).get(tf, len(ctx.a[tf]["close"]) - 1)
            if i < 30:
                continue
            marker = (spec["key"], ctx.symbol, _iso(ctx.close_utc(tf, i)))
            if marker in self.store.evaluated:
                continue
            self.store.evaluated.add(marker)
            try:
                decision = spec["decide"](ctx, i)
            except Exception as exc:                  # one strategy failing never stops the others
                self.store.rejections[spec["key"]][f"error: {type(exc).__name__}"] += 1
                continue
            if decision is None:
                continue
            signal, reason = confirm(spec, decision, ctx, i, quote, now, check_freshness)
            if signal is None:
                self.store.rejections[spec["key"]][reason] += 1
                continue
            if self.store.open_signal(spec["key"], ctx.symbol):
                self.store.rejections[spec["key"]]["duplicate: previous signal still open"] += 1
                continue
            self._attach(signal, now)
            self.store.put_signal(signal)
            new.append(signal)
        return new

    def _attach(self, signal: dict[str, Any], now: float) -> None:
        """Merge into an open opportunity on the same symbol and direction, or open a new one.
        Promotion gate: a strategy that may not alert (RESEARCH, not promoted) is attributed to an open
        opportunity if there is one, but never opens or owns one, so it can neither alert nor block a
        later alert from an approved strategy."""
        t = datetime.fromisoformat(signal["confirmed_at"]).timestamp()
        spec = rules.BY_KEY.get(signal["strategy_key"])
        if spec is not None and not rules.alerting(spec):
            signal["alert"] = "research only (not alerted)"
            for opp in self.store.opportunities.values():
                first = datetime.fromisoformat(opp["first_confirmed_at"]).timestamp()
                if opp["symbol"] == signal["symbol"] and opp["direction"] == signal["direction"] and 0 <= t - first <= OPPORTUNITY_WINDOW:
                    signal["opportunity_id"] = opp["opportunity_id"]
                    self.store.put_opportunity({**opp, "research_strategies": sorted(set(opp.get("research_strategies", [])) | {signal["strategy_name"]}),
                                                "research_signal_ids": opp.get("research_signal_ids", []) + [signal["signal_id"]]})
                    break
            return
        for opp in sorted(self.store.opportunities.values(), key=lambda o: o["first_confirmed_at"], reverse=True):
            if opp["symbol"] != signal["symbol"] or opp["direction"] != signal["direction"]:
                continue
            first = datetime.fromisoformat(opp["first_confirmed_at"]).timestamp()
            primary = self.store.signals.get(opp.get("primary_signal_id") or "")
            open_ = primary is None or primary.get("outcome_status") not in FINAL
            if 0 <= t - first <= OPPORTUNITY_WINDOW and open_:
                signal["opportunity_id"] = opp["opportunity_id"]
                signal["alert"] = "merged"
                self.store.put_opportunity({**opp, "strategies": sorted(set(opp["strategies"]) | {signal["strategy_name"]}),
                                            "signal_ids": opp["signal_ids"] + [signal["signal_id"]]})
                return
        production = [c for c in self.production_confirmations()
                      if c.get("symbol") == signal["symbol"] and c.get("direction") == signal["direction"] and c.get("shadow") is not True
                      and 0 <= t - datetime.fromisoformat(str(c.get("confirmed_at"))).timestamp() <= PRODUCTION_WINDOW]
        opp = {"opportunity_id": "opp_" + uuid.uuid4().hex, "symbol": signal["symbol"], "direction": signal["direction"],
               "first_confirmed_at": signal["confirmed_at"], "primary_signal_id": signal["signal_id"],
               "strategies": [signal["strategy_name"]], "signal_ids": [signal["signal_id"]],
               "production_confirmations": [c.get("setup_id") for c in production]}
        signal["opportunity_id"] = opp["opportunity_id"]
        signal["alert"] = "covered by a production alert" if production else "primary"
        self.store.put_opportunity(opp)


# ----- outcomes ---------------------------------------------------------------------------------------

def resolve_signal(signal: dict[str, Any], m15: list[dict[str, Any]], m1: list[dict[str, Any]] | None, now: datetime) -> dict[str, Any]:
    """Authoritative first-barrier outcome (signal_outcomes.resolve), plus the strategy's time exit."""
    import signal_outcomes
    confirmed = datetime.fromisoformat(signal["confirmed_at"])
    plan = {"direction": signal["direction"], "entry": signal["entry"], "stop_loss": signal["stop_loss"],
            "take_profit": signal["take_profit"]}
    exit_at = datetime.fromisoformat(signal["time_exit_at"]) if signal.get("time_exit_at") else None
    horizon = min(now, exit_at) if exit_at else now
    bars = [b for b in m15 if b["utc"] < horizon.timestamp()]
    minutes = [b for b in (m1 or []) if b["utc"] < horizon.timestamp()]
    result = signal_outcomes.resolve(plan, confirmed, bars, minutes, horizon)
    if result["status"] == "PENDING" and exit_at and now >= exit_at and bars:
        last = bars[-1]
        long = signal["direction"] == "LONG"
        price = last["close"] if long else last["close"] + float(last.get("spread") or 0)
        r = ((price - signal["entry"]) if long else (signal["entry"] - price)) / signal["risk"]
        result = {**result, "status": "TIME_EXIT", "hit_at": exit_at.isoformat(), "r_multiple": round(r, 4),
                  "reason": "the strategy's time exit came before either level"}
    return result


# ----- statistics ----------------------------------------------------------------------------------------

def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [r for r in rows if r.get("outcome_status") in ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")]
    rs = [float(r.get("r_multiple") or 0.0) for r in sorted(resolved, key=lambda r: str(r.get("outcome_at")))]
    wins = sum(x > 0 for x in rs)
    peak = equity = dd = 0.0
    for x in rs:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {"signals": len(rows), "resolved": len(resolved),
            "open": sum(r.get("outcome_status") not in FINAL for r in rows),
            "unresolvable": sum(r.get("outcome_status") in ("AMBIGUOUS", "UNAVAILABLE", "NO_HIT") for r in rows),
            "win_rate": round(wins / len(rs), 4) if rs else None,
            "expectancy_r": round(sum(rs) / len(rs), 4) if rs else None,
            "total_r": round(sum(rs), 3) if rs else None, "max_drawdown_r": round(dd, 3) if rs else None}


def statistics(store: BankStore, linked_rows: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    """One row per registered strategy (any number), from RECORDED signals and outcomes only."""
    rules.load_expansion()                 # admitted expansion strategies appear as soon as they are admitted
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in store.signals.values():
        by_key[s["strategy_key"]].append(s)
    out = []
    for spec in rules.SPECS:
        rows = (linked_rows or {}).get(spec["key"], []) if spec["status"] == rules.LINKED else by_key.get(spec["key"], [])
        summary = _summary(rows)
        by_inst: dict[str, list] = defaultdict(list)
        by_tf: dict[str, list] = defaultdict(list)
        for r in rows:
            by_inst[r["symbol"]].append(r)
            by_tf[r.get("timeframe") or spec["timeframe"]].append(r)
        from strategy_bank import qualification
        out.append({"n": spec["n"], "key": spec["key"], "name": spec["name"], "status": spec["status"],
                    "alerting": rules.alerting(spec), "qualification": qualification.current_status(spec["key"]),
                    "monitoring": spec["status"] != rules.UNSUPPORTED, "timeframe": spec["timeframe"], **summary,
                    "by_instrument": {k: _summary(v) for k, v in sorted(by_inst.items())},
                    "by_timeframe": {k: _summary(v) for k, v in sorted(by_tf.items())},
                    "rejections": dict(store.rejections.get(spec["key"], {})),
                    "unsupported_reason": spec.get("unsupported_reason")})
    return out


def linked_production_rows() -> dict[str, list[dict[str, Any]]]:
    """Strategies #1-3: production confirmations joined with their authoritative outcomes."""
    import signal_outcomes
    from observations import CONFIRMATIONS_FILE
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outcomes = {r["setup_id"]: r for r in signal_outcomes.OutcomeStore().all_latest()}
    if not CONFIRMATIONS_FILE.exists():
        return out
    with CONFIRMATIONS_FILE.open("rb") as handle:
        for line in handle:
            try:
                c = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if c.get("shadow") is True:
                continue
            for spec in rules.SPECS:
                link = spec.get("linked_to")
                if not link or c.get("strategy_id") != link["strategy_id"]:
                    continue
                if "setup_type" in link and str(c.get("setup_type") or "").upper() != link["setup_type"]:
                    continue
                o = outcomes.get(c.get("setup_id"), {})
                out[spec["key"]].append({"symbol": c.get("symbol"), "timeframe": c.get("timeframe") or "M15",
                                         "confirmed_at": c.get("confirmed_at"), "outcome_status": o.get("status"),
                                         "r_multiple": o.get("r_multiple"), "outcome_at": o.get("hit_at")})
    return out
