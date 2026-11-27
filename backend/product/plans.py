"""Subscription plan catalogue (provisional) and per-plan capabilities.

The commercial store (``commercial_store.entitlements``) currently persists only the legacy
plans ``free`` and ``pro`` (``pro`` = the $19/month plan in ``commercial.PRO_PRICE_USD``).
This module is the single product definition of the four planned tiers and maps the legacy
values onto them, so the database schema does not have to change before billing exists:

    legacy "free" -> FREE
    legacy "pro"  -> TRADER   (same $19 price and limits as today)

PROFESSIONAL and AUTOMATED are defined but cannot be granted yet: no stored plan maps to them
until a reviewed schema migration and a billing provider exist. Billing stays inactive.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

BILLING_ACTIVE = False          # payment processing is deliberately not integrated (Phase 8)
PRICES_PROVISIONAL = True

FREE, TRADER, PROFESSIONAL, AUTOMATED = "FREE", "TRADER", "PROFESSIONAL", "AUTOMATED"
ORDER = (FREE, TRADER, PROFESSIONAL, AUTOMATED)

# Instruments available on FREE today (commercial.FREE_SYMBOLS is the enforced source).
FREE_SYMBOLS = ("XAUUSD", "EURUSD", "GBPUSD")


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_usd_month: int
    summary: str
    history_days: int
    symbols: tuple[str, ...] | None          # None = full scanned universe
    watchlists: int
    exports: bool
    ai_analyst: bool
    strategy_lab: bool
    alerts: str                              # "none" | "delayed" | "realtime"
    execution: str                           # "none" | "demo_forward" (never "live" in this release)
    grantable: bool                          # can a stored entitlement map to it today?
    features: tuple[str, ...] = field(default_factory=tuple)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["symbols"] = list(self.symbols) if self.symbols is not None else None
        data["features"] = list(self.features)
        return data


PLANS: dict[str, Plan] = {
    FREE: Plan(FREE, "Free", 0, "Watch the market radar on core instruments.", 7, FREE_SYMBOLS, 1,
               False, False, False, "none", "none", True,
               ("Market Radar (3 instruments)", "Signal lifecycle view", "7-day signal history")),
    TRADER: Plan(TRADER, "Trader", 19, "Full radar, signal centre and journal for active traders.", 90, None, 5,
                 True, False, False, "realtime", "none", True,
                 ("Full instrument universe", "Signal Centre with outcomes", "90-day history", "Journal exports",
                  "Real-time alerts")),
    PROFESSIONAL: Plan(PROFESSIONAL, "Professional", 49, "Grounded AI analyst and strategy research tools.", 365, None, 20,
                       True, True, True, "realtime", "none", False,
                       ("Everything in Trader", "AI Market Analyst (data-grounded)", "Strategy Lab and evidence reports",
                        "Performance analytics", "1-year history")),
    AUTOMATED: Plan(AUTOMATED, "Automated", 99, "Connect a demo account for supervised automated forward testing.",
                    365, None, 50, True, True, True, "realtime", "demo_forward", False,
                    ("Everything in Professional", "Execution engine (demo accounts only)", "Risk limits and emergency stop",
                     "Execution logs")),
}

LEGACY_PLAN_MAP = {"free": FREE, "pro": TRADER}


def plan_for_legacy(value: str | None) -> Plan:
    """Map a stored entitlement value to its product plan; unknown or missing fails closed to FREE."""
    return PLANS[LEGACY_PLAN_MAP.get(str(value or "").lower(), FREE)]


def catalogue() -> dict[str, Any]:
    return {"billing_active": BILLING_ACTIVE, "prices_provisional": PRICES_PROVISIONAL, "currency": "USD",
            "plans": [PLANS[code].public() for code in ORDER],
            "notes": ["Prices are provisional and no payment is taken.",
                      "Live-money execution is not offered on any plan.",
                      "Strategy results shown in the product are recorded outcomes, never projections."]}


def allows(plan: Plan, capability: str) -> bool:
    """Capability check used by future route guards; unknown capabilities are denied."""
    checks = {"exports": plan.exports, "ai_analyst": plan.ai_analyst, "strategy_lab": plan.strategy_lab,
              "alerts": plan.alerts != "none", "execution": plan.execution != "none"}
    return bool(checks.get(capability, False))
