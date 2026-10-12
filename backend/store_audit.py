"""Read-only streaming audit. No account data or record contents are printed."""
import argparse
from collections import Counter
import json
from pathlib import Path
from outcome_identity import semantic_fingerprint


def audit_store(root: Path) -> dict:
    result = {}
    confirmations = set()
    outcomes = set()
    outcome_variants = {}
    confirmation_references = set()
    outcome_references = set()
    for name in ("setup_confirmations.jsonl", "market_outcomes.jsonl", "trade_outcomes.jsonl",
                 "setup_lifecycle.jsonl", "setup_observations.jsonl"):
        path = root / name
        counts = Counter()
        if not path.exists():
            result[name] = {"missing": True}
            continue
        with path.open("rb") as handle:
            for line in handle:
                counts["lines"] += 1
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("not an object")
                except (ValueError, UnicodeDecodeError):
                    counts["damaged_lines"] += 1
                    continue
                counts["valid_objects"] += 1
                if name == "setup_confirmations.jsonl":
                    key = row.get("setup_id")
                    counts["duplicate_setup_ids"] += key in confirmations
                    confirmations.add(key)
                    confirmation_references.add(row.get("observation_id"))
                if name == "market_outcomes.jsonl":
                    key = tuple(row.get(k) for k in ("setup_id", "observation_id", "horizon", "label_definition"))
                    counts["duplicate_outcome_keys"] += key in outcomes
                    outcomes.add(key)
                    variants = outcome_variants.setdefault(key, set())
                    fingerprint = semantic_fingerprint(row)
                    counts["duplicate_exact_copies"] += fingerprint in variants
                    counts["conflicting_extra_variants"] += bool(variants) and fingerprint not in variants
                    variants.add(fingerprint)
                    outcome_references.add(row.get("observation_id"))
                if name == "setup_observations.jsonl":
                    confirmation_references.discard(row.get("observation_id"))
                    outcome_references.discard(row.get("observation_id"))
                if name == "trade_outcomes.jsonl":
                    counts["invalid_execution_types"] += row.get("execution_type") not in {"ACTUAL", "SIMULATED"}
        result[name] = dict(counts)
        if name == "market_outcomes.jsonl":
            result[name]["conflicting_groups"] = sum(len(v) > 1 for v in outcome_variants.values())
    result["integrity"] = {
        "missing_confirmation_observation_ids": len(confirmation_references),
        "missing_outcome_observation_ids": len(outcome_references)}
    return result


if __name__ == "__main__":
    from storage_config import data_directory
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    print(json.dumps(audit_store(parser.parse_args().data_dir), indent=2))
