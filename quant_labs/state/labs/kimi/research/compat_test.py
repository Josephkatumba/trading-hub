"""Provider-interface compatibility test for Kimi Quant Lab models.

For each model source:
  1. validate_source() acceptance (live restricted-language gate).
  2. Decision-level agreement between direct module execution and the restricted
     model_host.execute() path on genuine historical snapshots (causal windows).
  3. Real bounded-worker execution (bounded_model subprocess, Windows job limits)
     proving the source runs inside the 4s CPU / 5s wall worker envelope.
Writes evidence JSON into research/results/compat_test.json.
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend"))

from quant_labs.data import SharedData
from quant_live.model_host import validate_source, execute
from quant_live.runtime import bounded_model
from quant_live.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import DATASET, TF, build_snapshot, load_module, load_symbol

MODELS = ["london_sweep_reversal", "vol_exhaustion_fade", "opening_range_drive"]
SAMPLES = [  # (symbol, list of close epochs to probe)
    ("EURUSD", [1729063800.0, 1730361600.0, 1754106000.0, 1761286800.0]),
    ("XAUUSD", [1729063800.0, 1745312400.0, 1761286800.0]),
    ("BTCUSD", [1730361600.0, 1751504400.0]),
]


def main():
    ds = SharedData(str(REPO / "quant_labs" / "state" / "shared"), DATASET)
    report = {"models": {}, "agreement_failures": 0}
    for key in MODELS:
        folder = Path(__file__).resolve().parents[1] / "strategies" / key
        source = (folder / "model.py").read_text(encoding="utf-8")
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        entry = {"validate_source": "PASS", "samples": [], "bounded_worker": None}
        try:
            validate_source(source)
        except Exception as exc:  # noqa: BLE001
            entry["validate_source"] = f"FAIL: {exc}"
        module = load_module(folder / "model.py")
        for symbol, times in SAMPLES:
            frames = load_symbol(ds, symbol)
            ftimes = {tf: [b["utc"] for b in frames[tf]] for tf in frames}
            for t in times:
                snap = build_snapshot(symbol, frames, ftimes, manifest["requirements"], t)
                direct = module.detect(snap) or []
                restricted = execute(source, snap)
                same = json.dumps(direct, sort_keys=True) == json.dumps(restricted, sort_keys=True)
                if not same:
                    report["agreement_failures"] += 1
                entry["samples"].append({"symbol": symbol, "asof": t, "n_decisions": len(direct),
                                         "agree": same})
        # real bounded worker on the last sample snapshot
        symbol, times = SAMPLES[0]
        frames = load_symbol(ds, symbol)
        ftimes = {tf: [b["utc"] for b in frames[tf]] for tf in frames}
        snap = build_snapshot(symbol, frames, ftimes, manifest["requirements"], times[-1])
        sha = __import__("hashlib").sha256(source.encode()).hexdigest()
        model = {"lab": "kimi", "key": key, "version": manifest["version"], "manifest": manifest,
                 "source": source, "sha": sha}
        store = Store(str(Path(__file__).resolve().parent / "results" / "compat_store"))
        t0 = time.time()
        result = bounded_model(store, model, snap)
        entry["bounded_worker"] = {"status": result.get("status"), "wall_s": round(time.time() - t0, 2),
                                   "resources": result.get("resources"), "decisions": len(result.get("decisions", []))}
        report["models"][key] = entry
        print(f"[compat] {key}: validate={entry['validate_source']} "
              f"samples={len(entry['samples'])} agree_failures="
              f"{sum(0 if s['agree'] else 1 for s in entry['samples'])} "
              f"worker={entry['bounded_worker']['status']}", flush=True)
    out = Path(__file__).resolve().parent / "results" / "compat_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("agreement_failures_total:", report["agreement_failures"])


if __name__ == "__main__":
    main()
