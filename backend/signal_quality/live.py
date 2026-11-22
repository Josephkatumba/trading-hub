"""Live quality assessment of a confirmed strategy-bank signal.

Mode (environment TRADEDEN_QUALITY_GATE):
  shadow   (default) every signal is graded and the grade, lifecycle stage and reasons are stored on the
           record; alerting is unchanged. This is the safe default while forward evidence accumulates.
  enforce  only A+ / A signals may open an opportunity and be alerted; everything else is stored as
           NO TRADE with its reasons (never deleted, still outcome-tracked for research).
  off      no grading.
Grading never places orders and never changes execution permissions.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Iterable

from signal_quality import features as feat
from signal_quality import lifecycle
from signal_quality.model import QualityModel, form_bucket

log = logging.getLogger(__name__)
_MODEL: QualityModel | None = None
_LOADED = False
_LOCK = threading.Lock()
RESOLVED = ("TARGET_HIT", "STOP_HIT", "TIME_EXIT")


def mode() -> str:
    value = os.getenv("TRADEDEN_QUALITY_GATE", "shadow").strip().lower()
    return value if value in ("shadow", "enforce", "off") else "shadow"


def model() -> QualityModel | None:
    global _MODEL, _LOADED
    with _LOCK:
        if not _LOADED:
            try:
                _MODEL = QualityModel.load()
            except Exception:                                  # a corrupt model must not stop scanning
                log.exception("quality model could not be loaded")
                _MODEL = None
            _LOADED = True
        return _MODEL


def recent_form(signals: Iterable[dict[str, Any]], strategy: str, window: int = 40) -> str:
    """Bucket of the strategy's last `window` resolved live signals (by outcome time)."""
    rows = sorted((s for s in signals if s.get("strategy_key") == strategy and s.get("outcome_status") in RESOLVED
                   and s.get("r_multiple") is not None), key=lambda s: str(s.get("outcome_at")))
    return form_bucket([float(s["r_multiple"]) for s in rows[-window:]])


def assess(ctx: Any, signal: dict[str, Any], history: Iterable[dict[str, Any]] = (),
           quality_model: QualityModel | None = None) -> dict[str, Any] | None:
    """Grade a confirmed bank signal from closed bars at its confirmation time; None when grading is off
    or unavailable."""
    if mode() == "off":
        return None
    m = quality_model or model()
    if m is None:
        return None
    try:
        at = datetime.fromisoformat(signal["confirmed_at"]).timestamp()
        computed = feat.compute(ctx, at, signal["strategy_key"], signal["direction"], float(signal["entry"]),
                                float(signal["stop_loss"]), signal.get("take_profit"))
        f = computed["features"]
        f["strategy_form"] = recent_form(history, signal["strategy_key"])
        graded = m.grade(f)
        stage = lifecycle.after_rules(graded)
        return {**graded, **stage, "mode": mode(), "regime": computed["raw"].get("regime", {}).get("regime"),
                "features": f, "suggested_exit": m.exits.get(signal["strategy_key"], "base")}
    except Exception:                                          # grading must never break a scan
        log.exception("quality assessment failed for %s", signal.get("signal_id"))
        return None
