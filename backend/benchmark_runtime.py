"""Windows read-only cold-index benchmark; optional observational scanner workload."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import time


class Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                  "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                  "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]]


def memory():
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    process = kernel.GetCurrentProcess()
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"private_mb": counters.PrivateUsage / 1048576, "working_mb": counters.WorkingSetSize / 1048576,
            "peak_private_mb": counters.PeakPagefileUsage / 1048576,
            "peak_working_mb": counters.PeakWorkingSetSize / 1048576}


def baseline_consume(self, handle, size):
    handle.seek(self.offset)
    data = handle.read(size - self.offset)
    end = data.rfind(b"\n")
    if end < 0:
        return
    position = self.offset
    for raw in data[:end + 1].split(b"\n")[:-1]:
        self._add(position, raw)
        self._unpersisted += 1
        position += len(raw) + 1
    self.offset = position
    self._head_hash, self._tail_hash = self._fingerprints(handle, self.offset)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("baseline", "stream"), default="stream")
    parser.add_argument("--scans", type=int, default=0)
    parser.add_argument("--numeric-threads", type=int, default=1)
    parser.add_argument("--clone-source", type=Path)
    parser.add_argument("--full-worker", action="store_true")
    args = parser.parse_args()
    if args.full_worker and not args.clone_source:
        parser.error("--full-worker requires --clone-source; original stores must never be benchmark writers")
    if args.clone_source:
        from recover_store import FILES
        import shutil
        args.data_dir.mkdir(parents=True, exist_ok=False)
        for name in FILES:
            if (args.clone_source / name).exists():
                shutil.copyfile(args.clone_source / name, args.data_dir / name)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = str(args.numeric_threads)
    os.environ["TRADING_HUB_DATA_DIR"] = str(args.data_dir.resolve())
    import jsonl_index
    if args.mode == "baseline":
        jsonl_index.JsonlIndex._consume = baseline_consume
    import observations
    from outcomes import market_outcome_index
    report = {"mode": args.mode, "numeric_threads": args.numeric_threads, "initial": memory(), "phases": []}
    for name, build in (("observations", observations._observation_index),
                        ("outcomes", market_outcome_index), ("lifecycle", observations._lifecycle_index)):
        started, cpu = time.perf_counter(), time.process_time()
        index = build()
        index.persist = False  # do not write sidecars in the historical reference
        index._loaded_sidecar = True  # force a reproducible cold build
        index.refresh()
        report["phases"].append({"name": name, "seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu, "rows": len(index.rows), **memory()})
    if args.scans:
        from unittest.mock import patch
        import main
        # Live MT5 reads and all four strategies; no writes or outcome derivation.
        from contextlib import ExitStack
        with ExitStack() as stack:
            if not args.full_worker:
                for name, value in (("record_markets", None), ("confirmation_events", []),
                                    ("outcome_watch_snapshots", []), ("snapshots_by_observation_id", {}),
                                    ("resolve_due_market_outcomes", [])):
                    stack.enter_context(patch.object(main, name, return_value=value))
            for number in range(args.scans):
                started, cpu = time.perf_counter(), time.process_time()
                markets = main.market_snapshot()
                report["phases"].append({"name": "full_worker_clone" if args.full_worker else "read_only_scan", "number": number + 1,
                    "markets": len(markets), "status": main._LAST_SCAN["status"],
                    "seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu, **memory()})
        main.close_mt5()
    print(json.dumps(report, indent=2))
