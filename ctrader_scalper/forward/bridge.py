"""TradeDen -> cTrader signal bridge (experiment fwd-tdn-001, DEMO).

    cd ctrader_scalper
    python -m forward.bridge            # runs until stopped (Ctrl+C)

Watches the two TradeDen signal streams written by the Trading Hub engine and appends every NEW signal, in a
flat normalised form, to Documents\\TradeDenScalper\\inbox\\tradeden_signals.jsonl. The cBot (copy mode) reads that
file, validates each signal and applies every risk rule before any order. This bridge never talks to a broker.

Sources (append-only JSONL written by the engine):
  garden : backend/data/telegram_notifications.jsonl   kind == "signal"     (trendline_v5 Telegram alerts)
  bank   : backend/data/strategy_bank/signals.jsonl     record_type == "bank_signal" and executable
History is NOT replayed: the bridge starts at the end of each file and only forwards signals confirmed within
MAX_AGE_SECONDS of the moment it sees them.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCES = {
    "garden": REPO / "backend" / "data" / "telegram_notifications.jsonl",
    "bank": REPO / "backend" / "data" / "strategy_bank" / "signals.jsonl",
}
MAX_AGE_SECONDS = 180
POLL_SECONDS = 3


def inbox_path() -> Path:
    env = os.getenv("TRADEDEN_INBOX")
    if env:
        return Path(env)
    docs = Path.home() / "OneDrive" / "Documents"
    if not docs.is_dir():
        docs = Path.home() / "Documents"
    return docs / "TradeDenScalper" / "inbox" / "tradeden_signals.jsonl"


def _ts(v) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def normalise(source: str, r: dict) -> dict | None:
    """Return a flat signal or None if the record is not a complete, executable trade instruction."""
    if source == "garden":
        if r.get("kind") != "signal":
            return None
        sid, strategy = r.get("setup_id"), r.get("strategy_id")
    else:
        if r.get("record_type") != "bank_signal" or r.get("executable") is False:
            return None
        sid, strategy = r.get("signal_id"), r.get("strategy_key")
    direction = str(r.get("direction", "")).upper()
    try:
        entry, stop, target = float(r["entry"]), float(r["stop_loss"]), float(r["take_profit"])
    except (KeyError, TypeError, ValueError):
        return None
    if not sid or direction not in ("LONG", "SHORT") or not r.get("symbol"):
        return None
    side = 1 if direction == "LONG" else -1
    if (entry - stop) * side <= 0 or (target - entry) * side <= 0:
        return None
    t = _ts(r.get("confirmed_at"))
    if t is None:
        return None
    out = {"signal_id": f"{source}:{sid}", "source": source, "strategy": str(strategy or ""), "symbol": str(r["symbol"]).upper(),
           "side": "buy" if side > 0 else "sell", "entry": entry, "stop": stop, "target": target,
           "timeframe": str(r.get("timeframe") or ""), "confirmed_at": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "time_exit_at": "", "bridged_at": ""}
    te = _ts(r.get("time_exit_at"))
    if te:
        out["time_exit_at"] = te.strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


class Tail:
    def __init__(self, path: Path):
        self.path = path
        self.pos = path.stat().st_size if path.exists() else 0     # start at the END: no history replay
        self.buf = ""

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.pos:          # rotated / truncated
            self.pos = 0
        if size == self.pos:
            return []
        with self.path.open("rb") as fh:
            fh.seek(self.pos)
            chunk = fh.read(size - self.pos)
        self.pos = size
        text = self.buf + chunk.decode("utf-8", "replace")
        parts = text.split("\n")
        self.buf = parts.pop()       # keep a partial last line for the next poll
        return [p for p in parts if p.strip()]


def run(once: bool = False, now=None) -> int:
    out = inbox_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    tails = {k: Tail(p) for k, p in SOURCES.items()}
    seen: set[str] = set()
    forwarded = 0
    print(f"bridge: watching {', '.join(str(p) for p in SOURCES.values())}\n        writing {out}", flush=True)
    while True:
        for source, tail in tails.items():
            for line in tail.lines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sig = normalise(source, rec)
                if sig is None or sig["signal_id"] in seen:
                    continue
                seen.add(sig["signal_id"])
                t_now = now() if now else datetime.now(timezone.utc)
                age = (t_now - _ts(sig["confirmed_at"])).total_seconds()
                if age > MAX_AGE_SECONDS:
                    continue         # an update to an old signal, not a new one
                sig["bridged_at"] = t_now.strftime("%Y-%m-%dT%H:%M:%SZ")
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(sig) + "\n")
                forwarded += 1
                print(f"{sig['bridged_at']} forwarded {sig['signal_id']} {sig['symbol']} {sig['side']} "
                      f"entry {sig['entry']} stop {sig['stop']} target {sig['target']}", flush=True)
        if once:
            return forwarded
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
