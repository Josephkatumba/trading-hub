"""Strategy confluence engine: when do INDEPENDENT strategies identify the same opportunity?

Strategies that read the same evidence are not independent: three ICT setups built on the same
liquidity sweep are one piece of evidence, not three. Every strategy therefore belongs to one evidence
family (what it actually measures), and confluence counts FAMILIES, never strategies or scores.

  family stage      the most advanced stage among its members that have a direction; members of one
                    family that disagree on direction make the family CONFLICTED (it votes for neither)
  agreement         families voting for the dominant direction minus families voting against it
  classification    NONE (fewer than 2 agreeing families), MIXED (opposing families present and net
                    agreement < 2), DIRECTIONAL AGREEMENT (>= 2 families agree, nothing confirmed),
                    CONFIRMED CONFLUENCE (>= 2 families agree AND at least one member has a confirmed
                    entry: a production confirmation, a closed-bar ICT confirmation or an open recorded
                    bank signal in that direction)
Directional agreement is context, not an entry. Agreement is also not evidence of edge: each
contributor carries its evidence tier, and the result says so when none is validated.
"""
from __future__ import annotations

from typing import Any

FAMILIES: dict[str, dict[str, Any]] = {
    "liquidity": {"label": "Liquidity & structure", "measures": "stop runs, sweeps and structure shifts",
                  "members": ("ict_sweep_reversal", "ict_mss", "ict_judas", "ict_sweep_fvg", "ict_silver_bullet", "liquidity_sweep",
                              "market_structure_break", "turtle_soup", "smc")},
    "imbalance": {"label": "Imbalance & PD arrays", "measures": "fair value gaps, order blocks, premium/discount",
                  "members": ("ict_fvg_continuation", "ict_ob_reversal", "ict_ote", "fair_value_gap", "order_block_retest")},
    "trend": {"label": "Trend & momentum", "measures": "moving-average trend, momentum and breakouts",
              "members": ("trend_momentum", "ema_crossover", "ema_pullback", "macd_momentum", "ichimoku", "donchian", "atr_breakout",
                          "breakout", "inside_bar_breakout", "kama", "heikin_ashi", "trend_pullback_v2", "momentum_v2", "breakout_v2",
                          "crypto_trend_v2")},
    "trendline": {"label": "Trendline", "measures": "trendline breaks, retests and bounces",
                  "members": ("trendline_v5", "trendline_break_retest", "trendline_bounce")},
    "levels": {"label": "Levels & mean reversion", "measures": "support/resistance reactions and stretched prices",
               "members": ("support_resistance", "bollinger_reversion", "prior_close_reversion", "rsi_divergence", "divergence_v2")},
    "session": {"label": "Session & time", "measures": "session ranges and opening breakouts",
                "members": ("london_breakout", "opening_range_breakout", "orb_v2", "fx_session_momentum", "weekend_gap")},
}
STAGE_RANK = {"NONE": 0, "IDLE": 0, "WATCHING": 1, "DETECTED": 1, "DEVELOPING": 2, "CONFIRMING": 3, "CONFIRMED": 4, "ACTIVE": 5}
VOTING_STAGE = 2                      # DEVELOPING or later votes; WATCHING is awareness only


def family_of(key: str) -> str | None:
    for fam, spec in FAMILIES.items():
        if any(key == m or key.startswith(m + "_") for m in spec["members"]):
            return fam
    return None


def _direction(value: Any) -> str | None:
    v = str(value or "").upper()
    return "LONG" if v in ("LONG", "BUY", "BULLISH") else "SHORT" if v in ("SHORT", "SELL", "BEARISH") else None


def contributors(market: dict[str, Any] | None, ict_setups: list[dict[str, Any]] | None, bank_signals: list[dict[str, Any]] | None,
                 tiers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Normalise production engines (radar), ICT stage reports and open bank signals into one list."""
    tiers = tiers or {}
    out = []
    for s in (market or {}).get("strategies") or []:
        sid = s.get("strategy_id") or ""
        lifecycle = str(s.get("lifecycle_state") or "").upper()
        stage = "CONFIRMED" if s.get("confirmed") is True and lifecycle in ("CONFIRMED", "ACTIVE") else str(s.get("state") or "NONE").upper()
        out.append({"key": sid, "name": sid.replace("_", " ").title(), "source": "production engine", "stage": stage,
                    "direction": _direction(s.get("direction")), "family": family_of(sid),
                    "confirmed_entry": stage == "CONFIRMED", "tier": tiers.get({"trendline_v5": "trendline_break_retest"}.get(sid, sid)),
                    "evidence": [f"score {s.get('score')}", f"setup family {s.get('setup_family') or '-'}"]})
    for e in ict_setups or []:
        if e.get("stage") in (None, "NONE"):
            continue
        out.append({"key": e["key"], "name": e["name"], "source": "ICT research (shadow)", "stage": e["stage"],
                    "direction": _direction(e.get("direction")), "family": family_of(e["key"]),
                    "confirmed_entry": e["stage"] == "CONFIRMED", "tier": tiers.get(e["key"]),
                    "evidence": list(e.get("evidence") or []), "missing": list(e.get("missing") or []), "blocked": e.get("blocked")})
    for s in bank_signals or []:
        if s.get("outcome_status") not in (None, "PENDING"):
            continue
        out.append({"key": s.get("strategy_key"), "name": s.get("strategy_name"), "source": "strategy bank signal",
                    "stage": "ACTIVE", "direction": _direction(s.get("direction")), "family": family_of(str(s.get("strategy_key") or "")),
                    "confirmed_entry": True, "tier": tiers.get(str(s.get("strategy_key"))),
                    "evidence": [f"recorded signal at {s.get('confirmed_at')}", f"entry {s.get('entry')} stop {s.get('stop_loss')} target {s.get('take_profit')}"]})
    return out


def assess(symbol: str, items: list[dict[str, Any]], bias: str | None = None) -> dict[str, Any]:
    fams: dict[str, dict[str, Any]] = {}
    for c in items:
        if not c.get("family") or not c.get("direction") or STAGE_RANK.get(c["stage"], 0) < VOTING_STAGE:
            continue
        f = fams.setdefault(c["family"], {"family": c["family"], "label": FAMILIES[c["family"]]["label"], "members": [], "directions": set()})
        f["members"].append(c)
        f["directions"].add(c["direction"])
    votes = {"LONG": [], "SHORT": []}
    conflicted = []
    for f in fams.values():
        f["stage"] = max((m["stage"] for m in f["members"]), key=lambda s: STAGE_RANK.get(s, 0))
        if len(f["directions"]) > 1:
            conflicted.append(f["label"])
            continue
        votes[next(iter(f["directions"]))].append(f)
    longs, shorts = len(votes["LONG"]), len(votes["SHORT"])
    direction = "LONG" if longs > shorts else "SHORT" if shorts > longs else None
    agree = votes[direction] if direction else []
    oppose = votes["SHORT" if direction == "LONG" else "LONG"] if direction else []
    net = len(agree) - len(oppose)
    confirmed = [m for f in agree for m in f["members"] if m.get("confirmed_entry")]
    if len(agree) < 2:
        cls = "NONE"
    elif oppose and net < 2:
        cls = "MIXED"
    elif confirmed:
        cls = "CONFIRMED CONFLUENCE"
    else:
        cls = "DIRECTIONAL AGREEMENT"
    tiers = {m.get("tier") for f in agree for m in f["members"]}
    validated = bool(tiers & {"VALIDATED", "PRODUCTION"})
    word = {"LONG": "bullish", "SHORT": "bearish"}.get(direction or "", "")
    if cls == "NONE":
        text = "No two independent evidence families agree on a direction." if (longs + shorts) else "No strategy is developing a setup."
    else:
        parts = [f"{f['label']} ({', '.join(sorted({m['name'] for m in f['members']}))}, {f['stage'].lower()})" for f in agree]
        text = f"{len(agree)} independent families are {word}: " + "; ".join(parts) + "."
        if oppose:
            text += f" Against: {', '.join(f['label'] for f in oppose)}."
        text += (" At least one has a confirmed entry." if confirmed else
                 " Directional agreement only: no contributor has confirmed an entry yet.")
    if bias and direction:
        aligned = (bias == "BULLISH") == (direction == "LONG") if bias in ("BULLISH", "BEARISH") else None
        htf = "agrees" if aligned else "disagrees" if aligned is False else "is neutral"
        text += f" H4 bias {htf}."
    caveat = None if validated or cls == "NONE" else "No contributing strategy has a validated historical edge: treat this as context, not as a trade signal."
    return {"symbol": symbol, "direction": direction, "classification": cls, "independent_families": len(agree),
            "opposing_families": len(oppose), "net_agreement": net, "conflicted_families": conflicted,
            "entry_confirmed": bool(confirmed) and cls == "CONFIRMED CONFLUENCE", "htf_bias": bias,
            "families": [{"family": f["family"], "label": f["label"], "direction": next(iter(f["directions"])) if len(f["directions"]) == 1 else None,
                          "stage": f["stage"], "members": [{k: m.get(k) for k in ("key", "name", "source", "stage", "direction", "tier", "confirmed_entry", "evidence", "missing", "blocked")}
                                                           for m in f["members"]]} for f in fams.values()],
            "explanation": text, "caveat": caveat,
            "method": "Counts independent evidence families (not strategies, not scores); WATCHING does not vote."}
