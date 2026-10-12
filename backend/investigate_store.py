"""Summarize corruption and duplicate differences without printing record values."""
from collections import Counter
import json
from pathlib import Path
from outcome_identity import outcome_key


def differing_paths(left, right, prefix=""):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in left.keys() | right.keys():
            path = prefix + "." + key if prefix else key
            if key not in left or key not in right:
                yield path
            else:
                yield from differing_paths(left[key], right[key], path)
    elif left != right:
        yield prefix


def investigate(root):
    report = {}
    for path in root.glob("*.jsonl"):
        damaged = Counter()
        seen = {}
        differences = Counter()
        conflicts = Counter()
        with path.open("rb") as handle, path.open("rb") as previous:
            offset = 0
            for raw in handle:
                try:
                    row = json.loads(raw)
                    if not isinstance(row, dict):
                        raise ValueError("not object")
                except (ValueError, UnicodeError):
                    damaged["lines"] += 1
                    damaged["bytes"] += len(raw)
                    damaged["nul_lines"] += b"\x00" in raw
                    damaged["object_markers"] += b'"record_type"' in raw
                    damaged["observation_id_markers"] += b'"observation_id"' in raw
                    try:
                        raw.decode("utf-8")
                    except UnicodeError:
                        damaged["invalid_utf8_lines"] += 1
                    offset += len(raw)
                    continue
                if path.name == "market_outcomes.jsonl":
                    key = outcome_key(row)
                    if key in seen:
                        start, length = seen[key]
                        previous.seek(start)
                        first = json.loads(previous.read(length))
                        differences.update(differing_paths(first, row))
                        conflicts["duplicate_keys"] += 1
                        conflicts["different_labels"] += first.get("label") != row.get("label")
                        conflicts["different_prices"] += any(first.get(k) != row.get(k) for k in
                            ("reference_price", "future_price", "maximum_favorable_excursion", "maximum_adverse_excursion"))
                    else:
                        seen[key] = (offset, len(raw))
                offset += len(raw)
        report[path.name] = {"damaged": dict(damaged), "duplicates": dict(conflicts),
                            "differing_paths": dict(sorted(differences.items()))}
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    print(json.dumps(investigate(parser.parse_args().source), indent=2))
