"""Keyed lookups over append-only JSONL stores.

`observations.py` imports `indexed_jsonl_records`, but the module was missing
from the working tree, which stopped the engine from importing at all. This is
the minimal correct implementation: a linear scan with the same tolerant
parsing as `observations._read_jsonl`. A persistent offset index can replace
the scan later without changing the call signature.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def indexed_jsonl_records(path: Path, key: str, value: Any) -> list[dict[str, Any]]:
    """Return every JSON object in `path` whose `key` field equals `value`."""
    if value is None or not path.exists():
        return []
    wanted = str(value)
    matches: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and key in record and str(record[key]) == wanted:
                matches.append(record)
    return matches
