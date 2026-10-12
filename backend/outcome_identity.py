"""Outcome identity excludes generation metadata, never prices or evidence."""
import hashlib
import json


def outcome_key(row):
    return tuple(row.get(k) for k in ("setup_id", "observation_id", "horizon", "label_definition"))


def semantic_fingerprint(row):
    meaningful = {k: v for k, v in row.items() if k not in {"outcome_id", "resolved_at"}}
    quality = meaningful.get("data_quality")
    if isinstance(quality, dict):
        meaningful["data_quality"] = {k: v for k, v in quality.items()
                                      if k not in {"observed_at", "source_age_seconds"}}
    return hashlib.sha256(json.dumps(meaningful, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def unique_outcomes(rows):
    """Collapse copies; retain conflicting variants, explicitly quarantined from metrics."""
    groups = {}
    output = []
    for row in rows:
        if row.get("record_type") not in (None, "market_outcome"):
            output.append(row)
            continue
        key = outcome_key(row)
        try:
            hash(key)
        except TypeError:
            output.append(row)
            continue
        # Legacy records with incomplete identity cannot safely be merged.
        if not all(value is not None and value != "" for value in key):
            output.append(row)
            continue
        fingerprints = groups.setdefault(key, {})
        fingerprint = semantic_fingerprint(row)
        if fingerprint in fingerprints:
            continue
        fingerprints[fingerprint] = len(output)
        output.append(row)
    for variants in groups.values():
        if len(variants) < 2:
            continue
        for position in variants.values():
            row = output[position]
            quality = dict(row.get("data_quality") or {})
            quality.update(status="QUARANTINED", flags=list(dict.fromkeys([
                *(quality.get("flags") or []), "DUPLICATE_OUTCOME_CONFLICT"])))
            output[position] = {**row, "data_quality": quality,
                                "outcome_status": "DUPLICATE_OUTCOME_CONFLICT"}
    return output
