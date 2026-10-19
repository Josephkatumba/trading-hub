"""How a confirmed signal is named and explained to a trader (Telegram). Presentation only.

Everything here is derived from what the strategy recorded on the confirmation snapshot;
nothing is recomputed, re-planned or inferred. When the evidence for a statement is not
recorded, the statement is left out, and when too little is recorded the rationale falls
back to a plain factual sentence.

Setup names map the strategies' own recorded families:
  trendline_v5  BREAK under trendline-first-v5.1 confirms only after the broken line was
                retested and rejected ("... retest rejected")  -> Break & Retest
                BREAK under v5 (break candle only)              -> Break
                REVERSAL = price touched the line and closed back on its side
                ("Trendline support/resistance rejection")      -> Bounce
                The engine records no separate trend-reversal classification, so no
                signal is labelled "Trendline Reversal".
  support_resistance  SR_BOUNCE / SR_BREAK_RETEST (+ the level's recorded type)
  trend_momentum      TM_PULLBACK_CONTINUATION
  smc                 SMC_CHOCH_SWEEP_REVERSAL / SMC_BOS_CONTINUATION
"""
from __future__ import annotations

import html
import math
from typing import Any

RATIONALE_VERSION = "rationale-v1"
MAX_WORDS = 35
STRATEGY_NAMES = {"trendline_v5": "Trendline", "trendline": "Trendline", "support_resistance": "Support & Resistance",
                  "trend_momentum": "Trend & Momentum", "smc": "Smart Money Concepts"}


def strategy_name(strategy_id: Any) -> str:
    return STRATEGY_NAMES.get(str(strategy_id), str(strategy_id or "Unknown").replace("_", " ").title())


def _evidence(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return (snapshot or {}).get("strategy_evidence") or {}


def _features(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return (snapshot or {}).get("features") or {}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _decimals(reference: Any) -> int:
    text = repr(float(reference)) if _number(reference) is not None else ""
    return min(8, len(text.split(".")[1])) if "." in text and "e" not in text else 2


def _level(value: Any, reference: Any) -> str | None:
    """A recorded level shown with the instrument's price precision (taken from the entry)."""
    number = _number(value)
    return None if number is None else f"{number:.{_decimals(reference)}f}"


def setup_name(strategy_id: str, snapshot: dict[str, Any] | None, direction: str | None) -> str:
    snapshot = snapshot or {}
    family = str(snapshot.get("setup_type") or _evidence(snapshot).get("family") or "").upper()
    if strategy_id in ("trendline_v5", "trendline"):
        label = str(_features(snapshot).get("trendline") or "")
        if family == "BREAK":
            retested = "retest rejected" in label or str(snapshot.get("strategy_version")) == "trendline-first-v5.1"
            return "Break & Retest" if retested else "Break"
        if family == "REVERSAL":
            return "Bounce"
        return "Setup"
    if strategy_id == "support_resistance":
        kind = str((_evidence(snapshot).get("level") or {}).get("type") or "").upper()
        if family == "SR_BREAK_RETEST":
            return {"SUPPORT": "Support Break & Retest", "RESISTANCE": "Resistance Break & Retest"}.get(kind, "Break & Retest")
        if family == "SR_BOUNCE":
            return {"SUPPORT": "Support Bounce", "RESISTANCE": "Resistance Rejection"}.get(kind, "Level Rejection")
    if strategy_id == "trend_momentum" and family == "TM_PULLBACK_CONTINUATION":
        return "Pullback Continuation"
    if strategy_id == "smc":
        if family == "SMC_CHOCH_SWEEP_REVERSAL":
            return "Liquidity Sweep & CHoCH"
        if family == "SMC_BOS_CONTINUATION":
            return "BOS Continuation"
    return family.replace("_", " ").title() or "Setup"


def _article(noun: str) -> str:
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def _words(text: str) -> int:
    return len(text.split())


def _sentence(parts: list[str], optional: list[str], first_only: bool = False) -> str:
    """Join required parts, then add optional clauses while under MAX_WORDS (with
    first_only: only the first alternative that fits)."""
    text = "".join(parts)
    for clause in optional:
        if _words(text + clause) <= MAX_WORDS:
            text += clause
            if first_only:
                break
    return text.rstrip(" ,;") + "."


def _trendline(snapshot: dict[str, Any], direction: str, timeframe: str) -> str | None:
    f = _features(snapshot)
    label = str(f.get("trendline") or "").lower()
    family = str(snapshot.get("setup_type") or "").upper()
    long = direction == "LONG"
    line = "rising support trendline" if "support" in label else "falling resistance trendline" if "resistance" in label else None
    if line is None:
        return None
    side = "above" if long else "below"
    bias = "bullish" if long else "bearish"
    support = []                              # recorded evidence that agrees with the direction
    structure = str(f.get("structure") or "")
    if structure.lower().startswith("higher highs" if long else "lower highs"):
        support.append("a higher-high, higher-low structure" if long else "a lower-high, lower-low structure")
    if str(f.get("price_action") or "").lower().startswith(bias):
        support.append(f"{bias} price action")
    if str(f.get("momentum") or "").upper() == bias.upper():
        support.append(f"{bias} momentum")
    optional = []
    for count in range(len(support), 0, -1):  # the longest evidence list that fits
        optional.append(", with " + (", ".join(support[:count - 1]) + " and " if count > 1 else "") + support[count - 1])
    if family == "BREAK" and setup_name("trendline_v5", snapshot, direction) == "Break & Retest":
        return _sentence([f"Price broke the {line}, retested it and closed {side} it with a rejection candle on {timeframe}"], optional, first_only=True)
    if family == "BREAK":
        return _sentence([f"Price closed {side} the {line} on {timeframe}"], optional, first_only=True)
    if family == "REVERSAL":
        return _sentence([f"Price tested the {line} and closed back {side} it on {timeframe}"], optional, first_only=True)
    return None


def _support_resistance(snapshot: dict[str, Any], direction: str, timeframe: str, entry: Any) -> str | None:
    e = _evidence(snapshot)
    level = e.get("level") or {}
    kind = str(level.get("type") or "").lower()
    price = _level(level.get("price"), entry)
    if kind not in ("support", "resistance") or price is None or not (e.get("rejection") or {}).get("confirmed"):
        return None
    reactions = level.get("reactions")
    detail = []
    if isinstance(reactions, int) and reactions > 0:
        detail.append(f"{reactions} prior reactions")
    if level.get("higher_timeframe_confluence"):
        detail.append("H4/D1 confluence")
    described = f"{kind} at {price}" + (f" ({', '.join(detail)})" if detail else "")
    if str(e.get("family") or snapshot.get("setup_type")).upper() == "SR_BREAK_RETEST":
        return _sentence([f"Price retested broken {described} and rejected it with a confirmed {timeframe} candle"], [])
    return _sentence([f"Price rejected {described} with a confirmed {timeframe} rejection candle"], [])


def _trend_momentum(snapshot: dict[str, Any], direction: str, timeframe: str, entry: Any) -> str | None:
    e = _evidence(snapshot)
    trend, momentum, pullback = e.get("trend") or {}, e.get("momentum") or {}, e.get("pullback") or {}
    rules = (e.get("confirmation") or {}).get("rules") or {}
    h4 = (trend.get("h4") or {}).get("direction")
    if h4 not in ("LONG", "SHORT") or not rules.get("resumption"):
        return None
    word = "uptrend" if h4 == "LONG" else "downtrend"
    parts = [f"H4 {word}" + (" with H1 aligned" if rules.get("h1_aligned") else "")]
    impulse, retrace = _number(momentum.get("impulse_atr")), _number(pullback.get("retracement"))
    optional = []
    if impulse is not None and retrace is not None and pullback.get("controlled"):
        parts.append(f"; after a {impulse:.1f} ATR impulse and a {retrace:.0%} pullback, price resumed "
                     f"{'higher' if direction == 'LONG' else 'lower'} on {timeframe}")
    else:
        parts.append(f"; price resumed {'higher' if direction == 'LONG' else 'lower'} after a pullback on {timeframe}")
    if ((trend.get("d1") or {}).get("status")) == "AGREES":
        optional.append(", with D1 agreeing")
    return _sentence(parts, optional)


def _smc(snapshot: dict[str, Any], direction: str, timeframe: str, entry: Any) -> str | None:
    e = _evidence(snapshot)
    rules = (e.get("confirmation") or {}).get("rules") or {}
    brk = (e.get("structure") or {}).get("last_break") or {}
    kind = {"CHOCH": "CHoCH", "BOS": "BOS"}.get(str(brk.get("kind")))
    if not kind or not rules.get("structure_shift", True):
        return None
    side = "bullish" if direction == "LONG" else "bearish"
    parts = [f"{timeframe} {side} {kind}"]
    sweep = e.get("liquidity_sweep") or {}
    if rules.get("liquidity") and _level(sweep.get("swept_level"), entry):
        parts[0] = f"Liquidity sweep of {_level(sweep.get('swept_level'), entry)} then an {timeframe} {side} {kind}"
    poi = e.get("poi") or {}
    candle = (e.get("candle_confirmation") or {}).get("pattern")
    if rules.get("poi_retest") and poi.get("type"):
        poi_name = "order block" if poi["type"] == "ORDER_BLOCK" else str(poi["type"]).replace("_", " ").lower()
        parts.append(f"; price retested the {poi_name}" + (f" and confirmed with {_article(str(candle).replace('_', ' '))} candle" if candle else ""))
    optional = []
    htf = (e.get("htf") or {}).get("trend")
    if rules.get("htf_aligned") and htf:
        optional.append(f", in line with the {str(htf).lower()} H4 trend")
    return _sentence(parts, optional)


def rationale(strategy_id: str, snapshot: dict[str, Any] | None, direction: str | None, timeframe: str | None = None,
              entry: Any = None) -> dict[str, Any]:
    """{"text", "basis", "version"}: basis is "evidence" when built from recorded strategy
    evidence, "fallback" when that evidence was insufficient."""
    timeframe = timeframe or (snapshot or {}).get("timeframe") or "M15"
    builders = {"trendline_v5": _trendline, "trendline": _trendline}
    text = None
    if snapshot and direction in ("LONG", "SHORT"):
        try:
            if strategy_id in builders:
                text = builders[strategy_id](snapshot, direction, timeframe)
            elif strategy_id == "support_resistance":
                text = _support_resistance(snapshot, direction, timeframe, entry)
            elif strategy_id == "trend_momentum":
                text = _trend_momentum(snapshot, direction, timeframe, entry)
            elif strategy_id == "smc":
                text = _smc(snapshot, direction, timeframe, entry)
        except (TypeError, ValueError, AttributeError, KeyError):
            text = None
    if text:
        return {"text": text[0].upper() + text[1:], "basis": "evidence", "version": RATIONALE_VERSION}
    return {"text": f"All {strategy_name(strategy_id)} confirmation rules passed on the {timeframe} chart.",
            "basis": "fallback", "version": RATIONALE_VERSION}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)
