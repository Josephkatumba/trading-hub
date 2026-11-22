"""Strict signal lifecycle: WATCHING -> DETECTED -> DEVELOPING -> CONFIRMING -> CONFIRMED -> ACTIVE -> RESOLVED.

A strategy's rules can only bring a setup to CONFIRMING ("the rules say yes"). It becomes CONFIRMED only
when the quality engine grades it A+ or A; otherwise it ends as NO_TRADE with the reasons recorded, which
is a normal, expected result. ACTIVE (the entry quote exists and the trade plan is live) and RESOLVED
(target, stop or time exit) follow from the outcome tracker.

This module is pure: it decides the stage for a record and never sends alerts or orders.
"""
from __future__ import annotations

from typing import Any

STAGES = ("WATCHING", "DETECTED", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE", "RESOLVED")
TERMINAL = ("RESOLVED", "NO_TRADE", "EXPIRED", "INVALIDATED")
RESOLVED_STATUSES = ("TARGET_HIT", "STOP_HIT", "TIME_EXIT", "NO_HIT")


def after_rules(quality: dict[str, Any] | None) -> dict[str, Any]:
    """Stage of a setup whose strategy rules have confirmed, given its quality assessment."""
    if not quality:
        return {"stage": "CONFIRMING", "decision": "UNGRADED", "reason": "no quality model loaded"}
    if quality.get("confirmable"):
        return {"stage": "CONFIRMED", "decision": "TRADE", "reason": f"grade {quality['grade']} (expected {quality['expected_r']:+.2f}R)"}
    why = "; ".join(quality.get("caps") or []) or f"grade {quality['grade']} (expected {quality['expected_r']:+.2f}R) is below A"
    return {"stage": "NO_TRADE", "decision": "NO TRADE", "reason": why}


def stage_of(signal: dict[str, Any]) -> str:
    """Current stage of a stored bank signal (quality-graded or legacy)."""
    status = signal.get("outcome_status")
    quality = signal.get("quality") or {}
    confirmed = quality.get("stage") == "CONFIRMED" if quality else True     # legacy signals were confirmed by rules alone
    if not confirmed:
        return quality.get("stage") or "NO_TRADE"
    if status in RESOLVED_STATUSES:
        return "RESOLVED"
    if status == "PENDING" or status is None:
        return "ACTIVE"
    return "CONFIRMED"
