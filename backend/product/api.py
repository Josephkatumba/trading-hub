"""Read-only product routes. No route here changes state.

GET /api/platform/plans                 plan catalogue (public in commercial mode)
GET /api/platform/strategies/evidence   evidence tier per strategy (operator view)
GET /api/platform/execution/status      execution gate, emergency stop, adapters (operator view)
GET /api/platform/modules               product modules and their honest maturity (operator view)

In ``TRADING_HUB_AUTH_MODE=oidc`` the commercial middleware keeps every route except
``/api/platform/plans`` private (403), like other research administration routes.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from product import evidence, execution_policy, plans

router = APIRouter(prefix="/api/platform", tags=["platform"])

# Maturity: LIVE (working, in use) / PARTIAL (exists, needs product work) / PLANNED (not built).
MODULES: list[dict[str, Any]] = [
    {"key": "market_radar", "name": "Market Radar", "maturity": "LIVE",
     "built_on": ["main.py /api/market/radar", "strategies/", "observations.py"],
     "gap": "Per-user watchlists; universe extras beyond the official ten are scanner config, not user choice."},
    {"key": "ai_analyst", "name": "AI Market Analyst", "maturity": "PARTIAL",
     "built_on": ["analyst.py (rule-based)", "market_intel/ (Gold/Bitcoin briefings)"],
     "gap": "Rule-based today; an LLM layer must only narrate engine-supplied facts."},
    {"key": "signal_centre", "name": "Signal Centre", "maturity": "PARTIAL",
     "built_on": ["setup lifecycle + outcomes", "strategy_bank signals", "signal_outcomes.py"],
     "gap": "One unified signal record across engine, bank and cBot; outcome table including losses and expiries."},
    {"key": "strategy_intelligence", "name": "Strategy Intelligence", "maturity": "PARTIAL",
     "built_on": ["strategy_bank/qualification.py", "research/edge_v2, research/v3", "ctrader_scalper/engine walk-forward"],
     "gap": "One strategy registry across bank, research and cBot; evidence tiers now exposed here."},
    {"key": "execution_engine", "name": "Execution Engine", "maturity": "PARTIAL",
     "built_on": ["product/execution_policy.py", "cTrader cBot demo gate"],
     "gap": "No server-side broker adapter; execution disabled by default by design."},
    {"key": "performance_analytics", "name": "Performance Analytics", "maturity": "PARTIAL",
     "built_on": ["performance.py", "strategy_lab.py", "src/behavior.js (journal)"],
     "gap": "Signal-level P&L/R calendar views and account equity from recorded fills."},
    {"key": "accounts_billing", "name": "Accounts & Subscriptions", "maturity": "PARTIAL",
     "built_on": ["commercial.py OIDC sessions", "commercial_store.py PostgreSQL", "product/plans.py"],
     "gap": "Four-tier entitlements need a schema migration; billing intentionally inactive."},
]


@router.get("/plans")
def get_plans() -> dict[str, Any]:
    return plans.catalogue()


@router.get("/strategies/evidence")
async def get_strategy_evidence() -> dict[str, Any]:
    return await asyncio.to_thread(evidence.live_catalogue)


@router.get("/execution/status")
def get_execution_status() -> dict[str, Any]:
    return execution_policy.status()


@router.get("/modules")
def get_modules() -> dict[str, Any]:
    return {"modules": MODULES}
