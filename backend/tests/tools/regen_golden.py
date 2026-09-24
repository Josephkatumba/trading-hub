"""Developer tool: regenerate the trendline baseline golden files.

Usage (from backend/):  python tests/tools/regen_golden.py

ONLY run this when a behaviour change is intended and approved. The golden
files are the proof that the existing trendline engine is unchanged; review
the resulting git diff exactly like a change to scanner or persistence logic.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import golden_support as g  # noqa: E402


def main() -> int:
    import observations
    g.SCANNER_GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    golden = {fixture["name"]: json.loads(g.canonical(g.scan(fixture))) for fixture in g.load_fixtures()}
    g.SCANNER_GOLDEN.write_text(json.dumps(golden, sort_keys=True, indent=1), encoding="utf-8")
    print(f"scanner golden: {len(golden)} fixtures -> {g.SCANNER_GOLDEN}")
    g.PERSISTENCE_GOLDEN.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        files = g.run_persistence(observations, Path(tmp))
    for name, data in files.items():
        (g.PERSISTENCE_GOLDEN / name).write_bytes(data)
        records = data.count(b"\n")
        print(f"persistence golden: {name} {len(data)} bytes, {records} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
