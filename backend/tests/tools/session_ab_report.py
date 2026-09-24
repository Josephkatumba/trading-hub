"""Developer tool: Phase 9 LEGACY vs CORRECTED session-time A/B report (read-only).

Usage (from backend/, MT5 terminal running):  python tests/tools/session_ab_report.py OUT.json

Reads MT5 history and the real JSONL store; writes nothing except OUT.json.
1. Walk-forward: every hour (every 4th M15 bar) Sep 2025 - now for the official
   instruments, plus every M15 bar in the weeks around the four DST changes.
2. Observation-anchored: every distinct stored trendline scan moment (symbol +
   last bar) that has raw MT5 epochs, rebuilt from MT5 history at its real
   observation time; the legacy replay is also compared with what was stored.
"""
from __future__ import annotations

import bisect
import collections
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import MetaTrader5 as mt5  # noqa: E402

import main  # noqa: E402
import observations  # noqa: E402
import session_ab  # noqa: E402
import time_reverification as tr  # noqa: E402
from market_time import normalize_mt5_epoch  # noqa: E402

BASIS = "America/New_York+07:00"
START = datetime(2025, 9, 1, tzinfo=timezone.utc)
DST_CHANGES = {"EU fall-back 2025-10-26": datetime(2025, 10, 26, tzinfo=timezone.utc),
               "US fall-back 2025-11-02": datetime(2025, 11, 2, tzinfo=timezone.utc),
               "US spring-forward 2026-03-08": datetime(2026, 3, 8, tzinfo=timezone.utc),
               "EU spring-forward 2026-03-29": datetime(2026, 3, 29, tzinfo=timezone.utc)}


def load(symbol: str, now: datetime):
    broker = main.mt5_symbol(symbol)
    if not broker:
        return None
    m15 = mt5.copy_rates_range(broker, mt5.TIMEFRAME_M15, START - timedelta(days=5), now + timedelta(days=1))
    h1 = mt5.copy_rates_range(broker, mt5.TIMEFRAME_H1, START - timedelta(days=15), now + timedelta(days=1))
    rows = lambda rates: [{"time": float(r["time"]), "open": float(r["open"]), "high": float(r["high"]),  # noqa: E731
                           "low": float(r["low"]), "close": float(r["close"])} for r in rates]
    m15, h1 = rows(m15), rows(h1)
    legacy_cache, corrected_cache = {}, {}
    for row in m15:
        epoch = row["time"]
        legacy_cache[epoch] = datetime.fromtimestamp(epoch, timezone.utc)
        stamp = normalize_mt5_epoch(epoch, BASIS)
        corrected_cache[epoch] = datetime.fromisoformat(stamp["normalized_utc"]) if stamp["normalization_status"] == "VERIFIED" else None
    bars, dropped = tr.normalized_bars(m15, BASIS)
    return {"broker": broker, "m15": m15, "h1": h1, "h1_times": [r["time"] for r in h1],
            "legacy": lambda row, c=legacy_cache: c[row["time"]], "corrected": lambda row, c=corrected_cache: c[row["time"]],
            "corrected_cache": corrected_cache, "outcome_bars": bars, "dropped": dropped}


def sample(symbol, data, index, now_utc, spread=0.0):
    rows = data["m15"][index - 299:index + 1]
    cut = bisect.bisect_right(data["h1_times"], rows[-1]["time"])
    return session_ab.run_pair(symbol, rows, data["h1"][max(0, cut - 160):cut], now_utc, data["legacy"], data["corrected"], spread)


class Tally:
    def __init__(self):
        self.total = collections.Counter()
        self.score_pairs = collections.Counter()
        self.crossings = collections.Counter()
        self.groups = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        self.examples = []

    def add(self, pair, keys):
        flags = {"samples": 1, "unchanged": not pair["context_changed"] and not pair["scan_changed"],
                 "context_changed": bool(pair["context_changed"]), "scanner_changed": bool(pair["scan_changed"]),
                 **{"context:" + k: True for k in pair["context_changed"]}, **{"scan:" + k: True for k in pair["scan_changed"]}}
        for name, value in flags.items():
            if value:
                self.total[name] += 1
                for group, key in keys.items():
                    self.groups[group][str(key)][name] += 1
        if pair["reason_changed"]:
            self.total["scan:reason_text"] += 1
        if pair["scan_changed"]:
            old, new = pair["legacy"]["scan"]["score"], pair["corrected"]["scan"]["score"]
            self.score_pairs[f"{old}->{new}"] += 1
            self.total["alignment gained (+2)" if new > old else "alignment lost (-2)"] += 1
            if any(min(old, new) < threshold <= max(old, new) for threshold in (50, 65)):
                self.total["score change crosses a state threshold (50/65)"] += 1
                legacy = pair["legacy"]["scan"]
                self.crossings[f"{legacy['state']} | family={legacy['setup_family']} | gate={legacy['trendline_gate']} | aligned={legacy['confirmation_alignment']}"] += 1
        if pair["scan_changed"] and len(self.examples) < 12:
            self.examples.append({"symbol": pair["symbol"], "now": pair["now"], "session": pair["session"],
                                  "changed": pair["scan_changed"], "legacy": pair["legacy"]["scan"], "corrected": pair["corrected"]["scan"],
                                  "legacy_london": [pair["legacy"]["context"][k] for k in ("london_date", "london_low", "london_high")],
                                  "corrected_london": [pair["corrected"]["context"][k] for k in ("london_date", "london_low", "london_high")]})

    def dump(self):
        return {"total": dict(self.total), "score_pairs": dict(self.score_pairs.most_common()), "threshold_crossings": dict(self.crossings.most_common()), "groups": {g: {k: dict(v) for k, v in sorted(d.items())} for g, d in self.groups.items()},
                "examples": self.examples}


def walk_forward(datasets, now):
    tally, dst_tally = Tally(), Tally()
    edges = collections.Counter()
    flips = []
    boundary = collections.Counter()
    for symbol, data in datasets.items():
        m15 = data["m15"]
        valid_prev = {"legacy": False, "corrected": False}
        for index in range(299, len(m15)):
            corrected_open = data["corrected_cache"][m15[index]["time"]]
            legacy_open = data["legacy"](m15[index])
            in_dst_week = any(abs((legacy_open - change).total_seconds()) <= 4 * 86400 for change in DST_CHANGES.values())
            if index % 4 and not in_dst_week:
                continue
            if corrected_open is None:
                boundary["scan instant not verifiable (DST gap/repeated hour)"] += 1
                continue
            now_utc = corrected_open + timedelta(minutes=7, seconds=30)
            if now_utc < START:
                continue
            window = m15[index - 299:index + 1]
            missing = sum(1 for row in window if data["corrected"](row) is None)
            if missing:
                boundary["windows containing DST-invalid bars (skipped in CORRECTED London window)"] += 1
            pair = sample(symbol, data, index, now_utc)
            scan = pair["legacy"]["scan"]
            keys = {"instrument": symbol, "setup_family": scan["setup_family"] or "none", "direction": scan["direction"] or "none",
                    "session": pair["session"], "month": now_utc.strftime("%Y-%m"),
                    "weekday": now_utc.strftime("%a"), "timeframe": "M15"}
            (dst_tally if in_dst_week else tally).add(pair, {**keys, "dst_window": next((n for n, c in DST_CHANGES.items()
                                                                                          if abs((legacy_open - c).total_seconds()) <= 4 * 86400), "none")})
            for side in ("legacy", "corrected"):
                valid = pair[side]["scan"]["strategy_valid"] is True
                if valid and not valid_prev[side]:
                    edges[side + "_confirmation_onsets"] += 1
                valid_prev[side] = valid
            if pair["legacy"]["scan"]["strategy_valid"] != pair["corrected"]["scan"]["strategy_valid"]:
                side = "legacy" if pair["legacy"]["scan"]["strategy_valid"] else "corrected"
                outcome = session_ab.counterfactual_outcome(symbol, pair[side]["scan"], now_utc, data["outcome_bars"], now)
                flips.append({"symbol": symbol, "now": now_utc.isoformat(), "valid_only_in": side, "outcome": outcome[0],
                              "horizon": outcome[1], "direction": pair[side]["scan"]["direction"], "family": pair[side]["scan"]["setup_family"]})
    return tally.dump(), dst_tally.dump(), dict(edges), flips, dict(boundary)


def observation_anchored(datasets, now):
    stored = [json.loads(line) for line in open(observations.LOG_FILE, "rb") if b'"setup_snapshot"' in line]
    firsts = {}
    for snap in stored:
        raw = ((snap.get("time_provenance") or {}).get("bar_open_time") or {}).get("raw_mt5_epoch")
        if raw is None or (snap.get("strategy_id") or "trendline") != "trendline":
            continue
        firsts.setdefault((snap["symbol"], float(raw)), snap)
    tally = Tally()
    fidelity = collections.Counter()
    confirmations = {c["observation_id"]: c for c in observations.confirmation_events()}
    stored_conf = collections.Counter()
    for (symbol, raw), snap in firsts.items():
        data = datasets.get(symbol)
        if data is None:
            fidelity["symbol unavailable"] += 1
            continue
        epochs = [row["time"] for row in data["m15"]]
        index = bisect.bisect_left(epochs, raw)
        if index >= len(epochs) or epochs[index] != raw or index < 299:
            fidelity["bar not in history"] += 1
            continue
        now_utc = datetime.fromisoformat(snap["observed_at"])
        pair = sample(symbol, data, index, now_utc, float((snap.get("features") or {}).get("spread") or 0.0))
        scan = pair["legacy"]["scan"]
        tally.add(pair, {"instrument": symbol, "setup_family": scan["setup_family"] or "none", "direction": scan["direction"] or "none",
                         "session": pair["session"], "timeframe": "M15"})
        stored_state = (snap.get("rule_evidence") or {}).get("scanner_state")
        fidelity["replayed"] += 1
        fidelity["legacy replay state == stored scanner state"] += scan["state"] == stored_state
        fidelity["legacy replay London high/low == stored"] += ((snap.get("session") or {}).get("london_high"), (snap.get("session") or {}).get("london_low")) == \
            (pair["legacy"]["context"]["london_high"], pair["legacy"]["context"]["london_low"])
        if snap["observation_id"] in confirmations:
            stored_conf["stored confirmations replayed"] += 1
            stored_conf["legacy replay still valid"] += scan["strategy_valid"] is True
            stored_conf["corrected replay valid"] += pair["corrected"]["scan"]["strategy_valid"] is True
            stored_conf["validity differs"] += scan["strategy_valid"] != pair["corrected"]["scan"]["strategy_valid"]
    return tally.dump(), dict(fidelity), dict(stored_conf), len(firsts)


def main_report(out: Path) -> int:
    started = time.perf_counter()
    mt5.initialize()
    now = datetime.now(timezone.utc)
    stored_symbols = {json.loads(line)["symbol"] for line in open(observations.LOG_FILE, "rb") if b'"setup_snapshot"' in line}
    datasets = {symbol: data for symbol in sorted(set(main.OFFICIAL_UNIVERSE) | stored_symbols) if (data := load(symbol, now))}
    mt5.shutdown()
    loaded = time.perf_counter() - started
    official = {s: d for s, d in datasets.items() if s in main.OFFICIAL_UNIVERSE}
    t0 = time.perf_counter()
    wf, dst, edges, flips, boundary = walk_forward(official, now)
    t_wf = time.perf_counter() - t0
    t0 = time.perf_counter()
    anchored, fidelity, stored_conf, distinct = observation_anchored(datasets, now)
    t_an = time.perf_counter() - t0
    report = {"basis": BASIS, "generated": now.isoformat(), "walk_forward": wf, "dst_windows": dst, "confirmation_onsets": edges,
              "eligibility_flips": flips,
              "boundary": boundary, "observation_anchored": anchored, "replay_fidelity": fidelity, "stored_confirmations": stored_conf,
              "distinct_stored_scan_moments": distinct, "dropped_dst_bars": {s: d["dropped"] for s, d in official.items()},
              "timing_seconds": {"load_mt5_history": round(loaded, 2), "walk_forward": round(t_wf, 2), "observation_anchored": round(t_an, 2)}}
    report["flip_outcomes"] = {f"{k[0]}:{k[1]}": v for k, v in collections.Counter((f["valid_only_in"], f["outcome"]) for f in flips).items()}
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("confirmation_onsets", "flip_outcomes", "boundary", "replay_fidelity", "stored_confirmations",
                                             "distinct_stored_scan_moments", "timing_seconds")}, indent=1))
    print("walk-forward totals:", report["walk_forward"]["total"])
    print("DST-window totals:", report["dst_windows"]["total"])
    print("observation-anchored totals:", report["observation_anchored"]["total"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main_report(Path(sys.argv[1] if len(sys.argv) > 1 else "session_ab_report.json")))
