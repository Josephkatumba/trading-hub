"""Developer tool: regenerate the trendline golden files.

Usage (from backend/):
    python tests/tools/regen_golden.py                    # persistence goldens of the registered trendline version
    python tests/tools/regen_golden.py --legacy-baseline  # ALSO the v3 baseline (scanner + persistence)

ONLY run this when a behaviour change is intended and approved. The golden
files are the proof that the existing trendline engine is unchanged; review
the resulting git diff exactly like a change to scanner or persistence logic.

The scanner golden and tests/fixtures/golden/persistence are the historical
trendline-first-v3 baseline; they are rewritten only with --legacy-baseline.
A new trendline version gets its own persistence directory
(golden_support.PERSISTENCE_GOLDEN_V4 for trendline-first-v4).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import golden_support as g  # noqa: E402


def write_persistence(directory: Path, legacy: bool) -> None:
    import observations
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        files = g.run_persistence(observations, Path(tmp), legacy=legacy)
    for name, data in files.items():
        (directory / name).write_bytes(data)
        print(f"persistence golden ({directory.name}): {name} {len(data)} bytes, {data.count(b'\n')} records")


def main(argv: list[str]) -> int:
    from strategies import REGISTRY, TRENDLINE
    version = REGISTRY.get(TRENDLINE).version
    if version != g.TRENDLINE_V4:
        print(f"registered trendline version is {version}; add its golden directory to golden_support first")
        return 1
    write_persistence(g.PERSISTENCE_GOLDEN_V4, legacy=False)
    if "--legacy-baseline" in argv:
        g.SCANNER_GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        golden = {fixture["name"]: json.loads(g.canonical(g.scan(fixture))) for fixture in g.load_fixtures()}
        g.SCANNER_GOLDEN.write_text(json.dumps(golden, sort_keys=True, indent=1), encoding="utf-8")
        print(f"scanner golden: {len(golden)} fixtures -> {g.SCANNER_GOLDEN}")
        write_persistence(g.PERSISTENCE_GOLDEN, legacy=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
