"""Offline, non-destructive recovery: immutable backup, raw quarantine, clean projection."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

FILES = ("setup_observations.jsonl", "setup_lifecycle.jsonl", "setup_confirmations.jsonl",
         "market_outcomes.jsonl", "trade_outcomes.jsonl")
TYPES = dict(zip(FILES, ("setup_snapshot", "setup_lifecycle_event", "setup_confirmation",
                        "market_outcome", "trade_outcome")))


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_store(source, target):
    """Capture fixed-length prefixes; reject changes to captured bytes (appends are allowed)."""
    target.mkdir(parents=True, exist_ok=False)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
    sizes = {name: (source / name).stat().st_size for name in FILES if (source / name).exists()}
    for name, size in sizes.items():
        digest = hashlib.sha256()
        with (source / name).open("rb") as original, (target / name).open("xb") as copy:
            remaining = size
            while remaining:
                chunk = original.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("Source truncated during backup")
                copy.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        check = hashlib.sha256()
        with (source / name).open("rb") as original:
            remaining = size
            while remaining:
                chunk = original.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("Source truncated during verification")
                check.update(chunk)
                remaining -= len(chunk)
        if check.hexdigest() != digest.hexdigest() or digest_file(target / name) != digest.hexdigest():
            raise RuntimeError("Backup hash mismatch")
        manifest["files"][name] = {"bytes": size, "sha256": digest.hexdigest()}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def recover_objects(raw, expected):
    """Recover complete embedded objects only; never guess a missing field or byte."""
    decoder = json.JSONDecoder()
    found = []
    end = 0
    for match in re.finditer(rb'\{', raw):
        if match.start() < end:
            continue
        text = raw[match.start():].decode("utf-8", errors="surrogateescape")
        try:
            row, length = decoder.raw_decode(text)
            encoded = text[:length].encode("utf-8", errors="strict")
            if (row.get("record_type") != expected or not isinstance(row.get("setup_id"), str)
                    or not row["setup_id"]):
                continue
            if expected in {"setup_snapshot", "market_outcome"} and not row.get("observation_id"):
                continue
            found.append((row, encoded))
            end = match.start() + len(encoded)
        except (ValueError, UnicodeError, AttributeError):
            continue
    return found


def recovery_projection(backup, destination):
    from outcome_identity import semantic_fingerprint, outcome_key
    destination.mkdir(parents=True, exist_ok=False)
    quarantine = destination / "quarantine"
    quarantine.mkdir()
    report = {"files": {}, "backup_verified": True}
    journal = (destination / "recovery_events.jsonl").open("x", encoding="utf-8")
    try:
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        for name in FILES:
            source = backup / name
            if not source.exists():
                continue
            if digest_file(source) != manifest["files"][name]["sha256"]:
                raise RuntimeError("Backup was modified: " + name)
            counts = Counter()
            fingerprints = {}
            with source.open("rb") as original, (destination / name).open("xb") as clean:
                offset = 0
                for number, raw in enumerate(original, 1):
                    counts["original_lines"] += 1
                    try:
                        row = json.loads(raw)
                        if not isinstance(row, dict):
                            raise ValueError("not an object")
                        candidates = [(row, raw.rstrip(b"\r\n"))]
                    except (ValueError, UnicodeError):
                        counts["damaged_lines"] += 1
                        candidates = recover_objects(raw, TYPES[name])
                        raw_name = f"{name}.{number}.bin"
                        (quarantine / raw_name).write_bytes(raw)
                        counts["recovered_objects"] += len(candidates)
                        counts["unrecoverable_lines"] += not bool(candidates)
                        journal.write(json.dumps({"file": name, "line": number, "offset": offset,
                            "length": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                            "raw": "quarantine/" + raw_name, "recovered_objects": len(candidates)}) + "\n")
                    for row, encoded in candidates:
                        if name == "market_outcomes.jsonl":
                            key, fingerprint = outcome_key(row), semantic_fingerprint(row)
                            try:
                                hash(key)
                                complete = all(value is not None and value != "" for value in key)
                            except TypeError:
                                complete = False
                            # Incomplete legacy identity cannot establish that two events are copies.
                            seen = fingerprints.setdefault(key, set()) if complete else set()
                            if fingerprint in seen:
                                counts["duplicate_copies_omitted"] += 1
                                journal.write(json.dumps({"file": name, "line": number, "offset": offset,
                                    "reason": "DUPLICATE_COPY", "semantic_sha256": fingerprint}) + "\n")
                                continue
                            counts["conflicting_variants_preserved"] += bool(seen)
                            seen.add(fingerprint)
                        clean.write(encoded + b"\n")
                        counts["output_records"] += 1
                    offset += len(raw)
            report["files"][name] = dict(counts)
            if fingerprints:
                report["files"][name]["conflicting_groups"] = sum(len(v) > 1 for v in fingerprints.values())
        report["output_hashes"] = {name: digest_file(destination / name) for name in FILES
                                   if (destination / name).exists()}
        (destination / "recovery_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        journal.close()


if __name__ == "__main__":
    import argparse
    from storage_config import data_directory
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=data_directory())
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    backup_store(args.source, args.output / "original")
    print(json.dumps(recovery_projection(args.output / "original", args.output / "recovered"), indent=2))
