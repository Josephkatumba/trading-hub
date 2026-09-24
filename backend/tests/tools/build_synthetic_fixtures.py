"""Developer tool: find deterministic synthetic bar series that exercise every
branch of scanner.analyze_symbol, and save them as fixtures.

Usage (from backend/):  python tests/tools/build_synthetic_fixtures.py

The saved fixtures are plain data; tests never import this generator. Each
fixture records which branch it covers so the coverage test can assert that
the fixture set still reaches every branch.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from scanner import analyze_symbol  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "scanner"
BASE_TIME = 1790000000.0


def series(seed: int, count: int, start: float, step_seconds: float, vol: float) -> list[dict]:
    rng = random.Random(seed)
    price, rows, drift = start, [], 0.0
    for i in range(count):
        if i % rng.randint(12, 30) == 0:
            drift = rng.uniform(-0.6, 0.6) * vol
        open_ = price
        close = open_ + drift + rng.gauss(0, vol)
        high = max(open_, close) + abs(rng.gauss(0, vol * 0.7))
        low = min(open_, close) - abs(rng.gauss(0, vol * 0.7))
        rows.append({"time": BASE_TIME + i * step_seconds, "open": round(open_, 5), "high": round(high, 5),
                     "low": round(low, 5), "close": round(close, 5)})
        price = close
    return rows


def branch(result: dict) -> str:
    valid = "valid" if result.get("strategy_valid") else "notvalid"
    family = result.get("setup_family") or "none"
    setup = str(result.get("setup", "")).lower().replace(" ", "_")
    return f"{result['state']}|{family}|{result.get('direction')}|{valid}|{setup}"


TARGETS = [
    "CONFIRMING|BREAK|LONG|valid", "CONFIRMING|BREAK|SHORT|valid",
    "CONFIRMING|REVERSAL|LONG|valid", "CONFIRMING|REVERSAL|SHORT|valid",
    "CONFIRMING|*|*|notvalid", "DEVELOPING|BREAK|*|*", "DEVELOPING|REVERSAL|*|*",
    "WATCHING|none|*|*",
]
# Not searched: a trendline event with score < 50 ("Trendline <family> watch").
# The scoring floor makes it practically unreachable (0 of ~18.5k real snapshots);
# test_scanner_snapshots covers it by forcing the scoring inputs instead.
# NO SETUP is built deterministically from a flat series (every source neutral).


def matches(target: str, key: str) -> bool:
    return all(t == "*" or t == k for t, k in zip(target.split("|"), key.split("|")))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    found: dict[str, dict] = {}
    sessions = [None, {"session": "London", "session_alignment": None},
                {"session": "New York", "session_alignment": "New York is retesting the London low, watch for bullish confirmation"}]
    for seed in range(1, 20000):
        rows = series(seed, 140, 100.0, 900.0, 0.35)
        higher = series(seed * 7 + 1, 90, 100.0, 3600.0, 0.8)
        context = sessions[seed % 3]
        result = analyze_symbol("SYN", rows, spread=0.02, session_context=context, higher_rows=higher)
        key = branch(result)
        for target in TARGETS:
            if target not in found and matches(target, key):
                found[target] = {"seed": seed, "rows": rows, "higher_rows": higher, "session_context": context, "branch": key}
        if len(found) == len(TARGETS):
            break
    missing = [t for t in TARGETS if t not in found]
    for index, (target, data) in enumerate(found.items()):
        name = "synthetic_%02d_%s" % (index, target.replace("|", "_").replace("*", "any").replace(" ", "_").lower())
        fixture = {"name": name, "symbol": "SYN", "source": f"synthetic seed {data['seed']}", "covers": target,
                   "spread": 0.02, "rows": data["rows"], "higher_rows": data["higher_rows"], "session_context": data["session_context"]}
        (OUT / f"{name}.json").write_text(json.dumps(fixture, separators=(",", ":")), encoding="utf-8")
        print(f"{target:36s} seed {data['seed']:5d}  {data['branch']}")
    flat = [{"time": BASE_TIME + i * 900.0, "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0} for i in range(120)]
    no_setup = {"name": "synthetic_no_setup_flat", "symbol": "SYN", "source": "synthetic flat series", "covers": "NO SETUP|none|*|*",
                "spread": 0.0, "rows": flat, "higher_rows": flat[:80], "session_context": None}
    (OUT / "synthetic_no_setup_flat.json").write_text(json.dumps(no_setup, separators=(",", ":")), encoding="utf-8")
    short = {"name": "synthetic_insufficient_data", "symbol": "SYN", "source": "synthetic, 40 rows", "covers": "insufficient",
             "spread": 0.0, "rows": series(3, 40, 100.0, 900.0, 0.35), "higher_rows": None, "session_context": None}
    (OUT / "synthetic_insufficient_data.json").write_text(json.dumps(short, separators=(",", ":")), encoding="utf-8")
    print("missing targets:", missing or "none")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
