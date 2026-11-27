"""Upgraded versions of existing bank strategies (strategy audit, 2026-11-26).

The historical bank backtest (data/strategy_bank/historical.json) found every T-034 strategy
unprofitable or unproven after costs. Changing thresholds on the same logic would only fit noise, so
each upgrade below changes the MARKET HYPOTHESIS behind a weak original, states that hypothesis, and
is registered as a NEW RESEARCH strategy (shadow: recorded, never alerted). The originals keep running
unchanged, so live behaviour and their records are preserved and the two can be compared.

Audit findings that motivated each upgrade (all-period expectancy after costs, from historical.json):
  breakout (-0.05R), donchian (-0.05R), atr_breakout (-0.07R), inside_bar (-0.10R): breakouts are taken
      in any volatility regime and any trend; most fail. -> breakout_v2: only from volatility compression,
      with a displacement close, aligned with the H4 trend, during liquid hours.
  ema_pullback (-0.10R, 221 trades/month): fires on any EMA20 tag, including in ranges; entry on the tag
      candle itself. -> trend_pullback_v2: trend regime required (ADX), H4 alignment, a deeper pullback
      into the EMA20-EMA50 zone, entry only when price resumes (close above the prior high), structural stop.
  macd_momentum (-0.03R, 181 trades/month), ema_crossover (-0.10R): momentum crosses in non-trending
      markets. -> momentum_v2: rising ADX >= 25 with DI agreement and H4 alignment, never overextended.
  rsi_divergence (-0.06R): divergence anywhere. -> divergence_v2: divergence only at a fresh two-day
      extreme (a liquidity sweep) and outside strong trends.
  opening_range_breakout (+0.00R, test -0.13R): any opening range. -> orb_v2: only normal-width ranges,
      breakout in the direction of the H1 trend, tighter stop at the range midpoint.
  crypto: no crypto-specific rule existed. -> crypto_trend_v2: H1 breakout of a 2-day high/low in the
      direction of the H4 trend (time-series momentum, e.g. Liu & Tsyvinski 2021), 3R target.
Parameters are fixed here before testing and are not tuned on results.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from strategy_bank import indicators as ind
from strategy_bank import rules
from strategy_bank.rules import ALL, CRYPTO, INDICES, Ctx, Decision, NEW_YORK, FRANKFURT, _ok

VERSION = "bank-upgrades-v1"


def _h4_trend(ctx: Ctx, at_utc: float) -> str | None:
    if "H4" not in ctx.a:
        return None
    j = ctx.last_closed("H4", at_utc)
    if j < 200:
        return None
    e50, e200 = ctx.get("H4", "ema", 50)[j], ctx.get("H4", "ema", 200)[j]
    return "UP" if e50 > e200 else "DOWN" if e50 < e200 else None


def _atr_pct(ctx: Ctx, tf: str):
    key = (tf, "atr_pct120")
    if key not in ctx._cache:
        ctx._cache[key] = ind.rolling_percentile(ctx.get(tf, "atr"), 120)
    return ctx._cache[key]


def _liquid_hours(ctx: Ctx, tf: str, i: int) -> bool:
    """07:00-20:00 UTC (London through New York) for non-crypto instruments."""
    if ctx.symbol in CRYPTO:
        return True
    hour = int(ctx.a[tf]["utc"][i] // 3600 % 24)
    return 7 <= hour < 20


def breakout_v2(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    """Volatility compression -> expansion breakout, trend-aligned."""
    a = ctx.a[tf]; o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    atr = ctx.get(tf, "atr")[i]
    hi, lo = ctx.get(tf, "prior_max", 20)[i], ctx.get(tf, "prior_min", 20)[i]
    pct = _atr_pct(ctx, tf)
    if i < 150 or not _ok(atr, hi, lo, pct[i - 1]) or not _liquid_hours(ctx, tf, i):
        return None
    if hi - lo > 2.5 * atr or pct[i - 1] > 0.35:                    # a real squeeze before the breakout bar
        return None
    trend = _h4_trend(ctx, ctx.close_utc(tf, i))
    rng = h[i] - l[i]
    for long in (True, False):
        if trend != ("UP" if long else "DOWN"):
            continue
        beyond = c[i] > hi + 0.1 * atr if long else c[i] < lo - 0.1 * atr
        body = (c[i] - o[i]) if long else (o[i] - c[i])
        strong = rng > 0 and body >= 0.6 * atr and ((c[i] - l[i]) if long else (h[i] - c[i])) >= 0.7 * rng
        first = c[i - 1] <= ctx.get(tf, "prior_max", 20)[i - 1] if long else c[i - 1] >= ctx.get(tf, "prior_min", 20)[i - 1]
        if beyond and strong and first:
            mid = (hi + lo) / 2
            stop = max(mid, c[i] - 1.5 * atr) if long else min(mid, c[i] + 1.5 * atr)
            if abs(c[i] - stop) < 0.8 * atr:
                stop = c[i] - 0.8 * atr if long else c[i] + 0.8 * atr
            return Decision("LONG" if long else "SHORT", stop=stop, evidence={"range_atr": (hi - lo) / atr, "atr_percentile": float(pct[i - 1])},
                            explanation=f"{tf} breakout from a volatility squeeze (ATR at the {pct[i - 1] * 100:.0f}th percentile, range {(hi - lo) / atr:.1f} ATR) "
                                        f"with a displacement close, aligned with the H4 trend. [{VERSION}]")
    return None


def trend_pullback_v2(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    """Trend-regime pullback into the EMA20-EMA50 zone; enter when price resumes."""
    a = ctx.a[tf]; o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    e20, e50, e200 = ctx.get(tf, "ema", 20), ctx.get(tf, "ema", 50), ctx.get(tf, "ema", 200)
    adx, plus, minus = ctx.get(tf, "adx")
    atr = ctx.get(tf, "atr")[i]; rsi = ctx.get(tf, "rsi")[i]
    if i < 220 or not _ok(atr, adx[i], rsi) or adx[i] < 20:
        return None
    trend = _h4_trend(ctx, ctx.close_utc(tf, i))
    for long in (True, False):
        if trend != ("UP" if long else "DOWN"):
            continue
        aligned = (e50[i] > e200[i] and e50[i] > e50[i - 10]) if long else (e50[i] < e200[i] and e50[i] < e50[i - 10])
        if not aligned:
            continue
        window = slice(i - 5, i)
        touched = (l[window] <= e20[window]).any() if long else (h[window] >= e20[window]).any()
        held = (c[window] >= e50[window] - 0.25 * atr).all() if long else (c[window] <= e50[window] + 0.25 * atr).all()
        resume = (c[i] > h[i - 1] and c[i] > e20[i] and c[i] > o[i]) if long else (c[i] < l[i - 1] and c[i] < e20[i] and c[i] < o[i])
        stretched = (rsi > 70) if long else (rsi < 30)
        if touched and held and resume and not stretched:
            ext = float(l[i - 5:i + 1].min()) if long else float(h[i - 5:i + 1].max())
            stop = ext - 0.25 * atr if long else ext + 0.25 * atr
            dist = abs(c[i] - stop)
            if dist > 3 * atr:
                return None
            if dist < 0.5 * atr:
                stop = c[i] - 0.5 * atr if long else c[i] + 0.5 * atr
            return Decision("LONG" if long else "SHORT", stop=stop, evidence={"adx": float(adx[i])},
                            explanation=f"Trend regime (ADX {adx[i]:.0f}, H4 aligned); pullback into the EMA20-EMA50 zone held, "
                                        f"and the {tf} close resumed beyond the prior candle. [{VERSION}]")
    return None


def momentum_v2(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    """MACD momentum only in a strengthening trend, aligned with H4, not overextended."""
    c = ctx.a[tf]["close"]; line, sig = ctx.get(tf, "macd"); e20 = ctx.get(tf, "ema", 20)
    adx, plus, minus = ctx.get(tf, "adx")
    atr = ctx.get(tf, "atr")[i]
    if i < 220 or not _ok(atr, adx[i], adx[i - 3], plus[i], minus[i]) or not _liquid_hours(ctx, tf, i):
        return None
    if adx[i] < 25 or adx[i] <= adx[i - 3]:
        return None
    trend = _h4_trend(ctx, ctx.close_utc(tf, i))
    for long in (True, False):
        if trend != ("UP" if long else "DOWN") or ((plus[i] <= minus[i]) if long else (minus[i] <= plus[i])):
            continue
        cross = (line[i] > sig[i] and line[i - 1] <= sig[i - 1] and line[i] > 0) if long else (line[i] < sig[i] and line[i - 1] >= sig[i - 1] and line[i] < 0)
        if cross and abs(c[i] - e20[i]) <= 1.5 * atr:
            return Decision("LONG" if long else "SHORT", stop_atr=1.5, evidence={"adx": float(adx[i])},
                            explanation=f"MACD cross in a strengthening trend (ADX {adx[i]:.0f} rising, DI agreeing, H4 aligned), price within 1.5 ATR of EMA20. [{VERSION}]")
    return None


def divergence_v2(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    """RSI divergence only where the second pivot swept a fresh two-day extreme, outside strong trends."""
    import bisect
    a = ctx.a[tf]; h, l, c = a["high"], a["low"], a["close"]
    rsi = ctx.get(tf, "rsi"); atr = ctx.get(tf, "atr")[i]
    adx = ctx.get(tf, "adx")[0]
    highs, lows = ctx.get(tf, "swing_points")
    if i < 80 or not _ok(atr, adx[i]) or adx[i] >= 30:
        return None
    for long, points in ((True, lows), (False, highs)):
        conf = ctx._cache.setdefault((tf, "conf_idx", long), [p[1] for p in points])
        k = bisect.bisect_right(conf, i) - 1
        if k < 1:
            continue
        (j1, _, p1), (j2, c2, p2) = points[k - 1], points[k]
        if not (5 <= j2 - j1 <= 40 and i - c2 <= 10 and j2 >= 51 and _ok(rsi[j1], rsi[j2])):
            continue
        swept = p2 < l[j2 - 48:j2 - 3].min() if long else p2 > h[j2 - 48:j2 - 3].max()
        trigger = h[j2] if long else l[j2]
        if long and swept and p2 < p1 and rsi[j2] > rsi[j1] and rsi[j1] < 35 and c[i] > trigger and c[i - 1] <= trigger:
            return Decision("LONG", stop=p2 - 0.3 * atr, evidence={"rsi_1": float(rsi[j1]), "rsi_2": float(rsi[j2])},
                            explanation=f"Bullish RSI divergence at a fresh two-day low (liquidity sweep), ADX {adx[i]:.0f}; close broke the pivot high. [{VERSION}]")
        if not long and swept and p2 > p1 and rsi[j2] < rsi[j1] and rsi[j1] > 65 and c[i] < trigger and c[i - 1] >= trigger:
            return Decision("SHORT", stop=p2 + 0.3 * atr, evidence={"rsi_1": float(rsi[j1]), "rsi_2": float(rsi[j2])},
                            explanation=f"Bearish RSI divergence at a fresh two-day high (liquidity sweep), ADX {adx[i]:.0f}; close broke the pivot low. [{VERSION}]")
    return None


def orb_v2(ctx: Ctx, i: int, tf: str = "M15") -> Decision | None:
    """Index opening-range breakout: normal-width range, H1-trend direction, midpoint stop."""
    zone = {"NAS100": NEW_YORK, "US500": NEW_YORK, "GER40": FRANKFURT}.get(ctx.symbol)
    if zone is None or "H1" not in ctx.a:
        return None
    a = ctx.a[tf]; utc = a["utc"]; o, h, l, c = a["open"], a["high"], a["low"], a["close"]
    local = datetime.fromtimestamp(utc[i], timezone.utc).astimezone(zone)
    (oh, om), (ch, cm) = ((9, 30), (16, 0)) if zone is NEW_YORK else ((9, 0), (17, 30))
    session_open = local.replace(hour=oh, minute=om, second=0, microsecond=0)
    minutes = (local - session_open).total_seconds() / 60
    if not (30 <= minutes < 150):
        return None
    start = session_open.timestamp()
    s, e = int(np.searchsorted(utc, start, side="left")), int(np.searchsorted(utc, start + 1800, side="left"))
    if e - s != 2:
        return None
    rng_h, rng_l = float(h[s:e].max()), float(l[s:e].min())
    j = ctx.last_closed("H1", ctx.close_utc(tf, i))
    if j < 60:
        return None
    h1_atr = ctx.get("H1", "atr")[j]
    e20, e50 = ctx.get("H1", "ema", 20)[j], ctx.get("H1", "ema", 50)[j]
    if not _ok(h1_atr) or not (0.5 * h1_atr <= rng_h - rng_l <= 2.0 * h1_atr):
        return None
    for long in (True, False):
        if (e20 <= e50) if long else (e20 >= e50):
            continue
        beyond = (lambda x: x > rng_h) if long else (lambda x: x < rng_l)
        if beyond(c[i]) and not any(beyond(x) for x in c[e:i]):
            close_t = local.replace(hour=ch, minute=cm, second=0, microsecond=0).timestamp()
            return Decision("LONG" if long else "SHORT", stop=(rng_h + rng_l) / 2,
                            max_bars=max(1, int((close_t - (utc[i] + 900)) // 900)),
                            evidence={"or_high": rng_h, "or_low": rng_l, "or_h1_atr": (rng_h - rng_l) / h1_atr},
                            explanation=f"Opening-range breakout in the H1 trend direction (EMA20 vs EMA50); range {(rng_h - rng_l) / h1_atr:.1f} H1 ATR; stop at the range midpoint. [{VERSION}]")
    return None


def crypto_trend_v2(ctx: Ctx, i: int, tf: str = "H1") -> Decision | None:
    """BTC/ETH: H1 close beyond the prior 48-bar extreme in the direction of the H4 trend, ADX >= 20."""
    c = ctx.a[tf]["close"]
    hi, lo = ctx.get(tf, "prior_max", 48), ctx.get(tf, "prior_min", 48)
    adx = ctx.get(tf, "adx")[0]
    atr = ctx.get(tf, "atr")[i]
    if i < 220 or not _ok(atr, hi[i], lo[i], hi[i - 1], lo[i - 1], adx[i]) or adx[i] < 20:
        return None
    trend = _h4_trend(ctx, ctx.close_utc(tf, i))
    if trend == "UP" and c[i] > hi[i] and c[i - 1] <= hi[i - 1]:
        return Decision("LONG", stop_atr=2.0, target_r=3.0, evidence={"adx": float(adx[i])},
                        explanation=f"Crypto trend breakout: H1 close above the 2-day high with the H4 trend up (ADX {adx[i]:.0f}). [{VERSION}]")
    if trend == "DOWN" and c[i] < lo[i] and c[i - 1] >= lo[i - 1]:
        return Decision("SHORT", stop_atr=2.0, target_r=3.0, evidence={"adx": float(adx[i])},
                        explanation=f"Crypto trend breakdown: H1 close below the 2-day low with the H4 trend down (ADX {adx[i]:.0f}). [{VERSION}]")
    return None


def _spec(key, name, decide, tf, instruments, replaces, hypothesis, entry, confirmation, stop, take_profit, min_rr=1.5, data=("H1", "H4")):
    return {"key": key, "name": name, "status": rules.RESEARCH, "decide": decide, "timeframe": tf, "instruments": instruments,
            "entry": entry, "indicators": "see strategy_bank/upgrades.py", "confirmation": confirmation, "stop": stop,
            "take_profit": take_profit, "min_rr": min_rr, "invalidation": rules.COMMON_INVALIDATION, "data": list(data),
            "family": "UPGRADE", "replaces": replaces, "hypothesis": hypothesis, "version": VERSION}


UPGRADES: list[dict[str, Any]] = [
    _spec("breakout_v2", "Compression Breakout v2", breakout_v2, "H1", ALL, ["breakout", "donchian", "atr_breakout", "inside_bar_breakout"],
          "Volatility clusters: breakouts that start from a squeeze, close with displacement and agree with the higher-timeframe trend follow through more often than breakouts in any regime.",
          "H1 close beyond the prior 20-bar range by 0.1 ATR (first close), when the range is <= 2.5 ATR and the previous bar's ATR is at or below the 35th percentile of the last 120 bars; body >= 0.6 ATR closing in the outer 30% of the candle; H4 EMA50/EMA200 aligned; 07-20 UTC (crypto any time).",
          "Completed H1 displacement close beyond the squeeze range.", "Range midpoint or 1.5 ATR (whichever is closer), at least 0.8 ATR.", "2R."),
    _spec("trend_pullback_v2", "Trend Pullback v2", trend_pullback_v2, "H1", ALL, ["ema_pullback", "ema_crossover", "ichimoku"],
          "Pullbacks only pay in a trending regime, and entering on resumption (not on the touch) avoids catching the pullbacks that become reversals.",
          "ADX(14) >= 20; H4 EMA50 vs EMA200 and H1 EMA50 vs EMA200 aligned with EMA50 sloping; in the last 5 bars price tagged EMA20 without closing more than 0.25 ATR beyond EMA50; the H1 close breaks the prior candle's extreme in the trend direction, beyond EMA20; RSI not stretched (70/30).",
          "Resumption close.", "0.25 ATR beyond the 5-bar pullback extreme (0.5-3 ATR).", "2R."),
    _spec("momentum_v2", "Trend Momentum v2", momentum_v2, "H1", ALL, ["macd_momentum", "ema_crossover"],
          "Momentum crosses carry information only when trend strength is rising; in flat markets they are noise.",
          "MACD(12,26,9) crosses its signal on the trend side of zero while ADX >= 25 and higher than 3 bars ago, DI in the trade direction, H4 aligned, price within 1.5 ATR of EMA20, 07-20 UTC.",
          "Completed H1 candle with all conditions.", "1.5 ATR.", "2R."),
    _spec("divergence_v2", "Liquidity Divergence v2", divergence_v2, "H1", ALL, ["rsi_divergence"],
          "Momentum divergence marks exhaustion only where stops were just taken (a fresh two-day extreme) and the market is not in a strong trend.",
          "RSI(14) divergence between two 3-bar swing pivots 5-40 bars apart (first RSI beyond 35/65) where the second pivot exceeds the extreme of the previous 48 bars; ADX < 30; first close through the second pivot candle within 10 bars.",
          "Structure break after the divergence.", "0.3 ATR beyond the second pivot.", "2R."),
    _spec("orb_v2", "Opening Range Breakout v2", orb_v2, "M15", INDICES, ["opening_range_breakout"],
          "Opening ranges of normal width broken in the direction of the prevailing intraday trend continue; very narrow or very wide ranges are noise or exhaustion.",
          "First M15 close beyond the first 30 minutes' range of the cash session within two hours, when the range is 0.5-2.0 H1 ATR and the H1 EMA20 vs EMA50 agrees with the direction.",
          "Completed M15 close beyond the opening range.", "Opening-range midpoint.", "2R; exit at the session close.", data=("M15", "H1")),
    _spec("crypto_trend_v2", "Crypto Trend Breakout v2", crypto_trend_v2, "H1", CRYPTO, ["donchian", "breakout"],
          "Crypto returns show time-series momentum: breakouts of the 2-day range in the direction of the H4 trend, with room to run (3R), capture it.",
          "BTCUSD/ETHUSD: first H1 close beyond the prior 48-bar high/low, H4 EMA50 vs EMA200 in the direction, ADX(14) >= 20.",
          "Completed H1 close beyond the 2-day extreme.", "2 ATR.", "3R.", min_rr=2.0),
]
BY_KEY = {s["key"]: s for s in UPGRADES}


def register() -> list[str]:
    added = []
    for spec in UPGRADES:
        if spec["key"] not in rules.BY_KEY:
            rules.register(spec)
            added.append(spec["key"])
    return added
