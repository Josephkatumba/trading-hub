"""Read-only verification of recovery backups, projection hashes and raw quarantine bytes."""
import argparse
import hashlib
import json
from pathlib import Path
from recover_store import digest_file


def verify(root):
    manifest=json.loads((root/"original/manifest.json").read_text(encoding="utf-8"))
    for name,entry in manifest["files"].items():
        if digest_file(root/"original"/name)!=entry["sha256"]:
            raise RuntimeError("Original backup checksum mismatch: "+name)
    report=json.loads((root/"canonical/recovery_report.json").read_text(encoding="utf-8"))
    for name,expected in report["output_hashes"].items():
        if digest_file(root/"canonical"/name)!=expected:
            raise RuntimeError("Projection checksum mismatch: "+name)
    quarantined=0
    with (root/"canonical/recovery_events.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            event=json.loads(line)
            if "raw" not in event:continue
            path=(root/"canonical"/event["raw"]).resolve()
            if not path.is_relative_to((root/"canonical/quarantine").resolve()):raise RuntimeError("Unsafe quarantine path")
            raw=path.read_bytes()
            if len(raw)!=event["length"] or hashlib.sha256(raw).hexdigest()!=event["sha256"]:
                raise RuntimeError("Quarantine checksum mismatch")
            quarantined+=1
    return {"backup_files_verified":len(manifest["files"]),"projection_files_verified":len(report["output_hashes"]),
            "quarantined_lines_verified":quarantined,"modified":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("root",type=Path)
    print(json.dumps(verify(parser.parse_args().root),indent=2))
