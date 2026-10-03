"""Synthetic, hand-built bars for the SMC strategy tests (deterministic; no MT5).

bullish_bos(ending) builds an M15 history in a rising structure (higher highs and
higher lows), a pullback ending in a bearish order-block candle, a three-candle
bullish displacement with a fair value gap that closes above the last swing high
(BOS), a retrace into the order block and, by `ending`:
  "reaction"     a wick-rejection candle closing back above the order block (CONFIRMING)
  "in_poi"       the retrace bar is the last closed bar, no reaction yet (DEVELOPING)
  "no_retrace"   the displacement is the last closed bar (WATCHING)
  "invalidated"  the retrace closes below the order block (NO SETUP)
H4 rises in a zigzag (bullish structure). H1 falls in a zigzag whose last swing high, 10 above
the close, is the nearest H1 swing high above entry
(the buy-side liquidity target). bearish(...) mirrors every price around a pivot.
"""
from __future__ import annotations

M15_SECONDS, H1_SECONDS, H4_SECONDS = 900, 3600, 14400
START = 1_750_000_000.0


def _bar(t: float, open_: float, high: float, low: float, close: float) -> dict:
    return {"time": t, "open": open_, "high": high, "low": low, "close": close}


def zigzag(start: float, legs: list[tuple[int, float]], step: float, t0: float) -> list[dict]:
    """Bars following straight legs (bars, move); a 0.1 wick on the close side only, so every
    turning bar is a strict fractal pivot."""
    bars, price, t = [], start, t0
    for count, move in legs:
        for _ in range(count):
            close = price + move / count
            up = close >= price
            bars.append(_bar(t, price, close + 0.1 if up else price, price if up else close - 0.1, close))
            price, t = close, t + step
    return bars


def _m15_base() -> list[dict]:
    legs = []
    for _ in range(14):                         # +4 / -2.5: higher highs and higher lows
        legs += [(6, 4.0), (6, -2.5)]
    bars = zigzag(79.0, legs, M15_SECONDS, START)
    # Rebase so the last pullback ends at 100.6 (just above the order block below).
    shift = 100.6 - bars[-1]["close"]
    return [{**b, **{k: b[k] + shift for k in ("open", "high", "low", "close")}} for b in bars]


def bullish_bos(ending: str = "reaction") -> dict[str, list[dict]]:
    m15 = _m15_base()
    t = m15[-1]["time"] + M15_SECONDS
    tail = [
        (100.6, 100.7, 99.8, 100.0),     # order block: the last bearish candle before the displacement
        (100.0, 102.1, 99.9, 102.0),     # displacement 1
        (102.0, 104.6, 101.9, 104.5),    # displacement 2 (FVG: next low 104.3 > 102.1)
        (104.5, 105.7, 104.3, 105.5),    # displacement 3: closes above the last swing high -> BOS
        (105.5, 105.6, 103.4, 103.5),    # retrace
        (103.5, 103.6, 100.3, 101.0),    # retrace into the order block [99.8, 100.7] (first tap)
        (101.2, 101.9, 100.2, 101.8),    # reaction: lower wick 1.0 of 1.7 range, closes above the block
    ]
    if ending == "in_poi":
        tail = tail[:-1]
    elif ending == "no_retrace":
        tail = tail[:4]
    elif ending == "invalidated":
        tail = tail[:-2] + [(103.5, 103.6, 99.0, 99.4)]
    for open_, high, low, close in tail:
        m15.append(_bar(t, open_, high, low, close))
        t += M15_SECONDS
    last = m15[-1]["close"]
    m15.append(_bar(t, last, last, last, last))                   # the forming bar
    h1 = zigzag(200.0, [(5, 6.0), (5, -10.0)] * 10, H1_SECONDS, START - 70 * H1_SECONDS)
    shift = 101.0 - h1[-1]["close"]                                 # falling zigzag: the last swing high, 10 above, is the nearest
    h1 = [{**b, **{k: b[k] + shift for k in ("open", "high", "low", "close")}} for b in h1]
    h1.append(_bar(h1[-1]["time"] + H1_SECONDS, 101.0, 101.0, 101.0, 101.0))
    h4 = zigzag(40.0, [(4, 10.0), (4, -5.0)] * 6, H4_SECONDS, START - 60 * H4_SECONDS)
    h4.append(_bar(h4[-1]["time"] + H4_SECONDS, h4[-1]["close"], h4[-1]["close"], h4[-1]["close"], h4[-1]["close"]))
    return {"M15": m15, "H1": h1, "H4": h4}


def _htf(frames_m15: list[dict]) -> dict[str, list[dict]]:
    h1 = zigzag(200.0, [(5, 6.0), (5, -10.0)] * 10, H1_SECONDS, START - 70 * H1_SECONDS)
    shift = 101.0 - h1[-1]["close"]
    h1 = [{**b, **{k: b[k] + shift for k in ("open", "high", "low", "close")}} for b in h1]
    h1.append(_bar(h1[-1]["time"] + H1_SECONDS, 101.0, 101.0, 101.0, 101.0))
    h4 = zigzag(40.0, [(4, 10.0), (4, -5.0)] * 6, H4_SECONDS, START - 60 * H4_SECONDS)
    h4.append(_bar(h4[-1]["time"] + H4_SECONDS, h4[-1]["close"], h4[-1]["close"], h4[-1]["close"], h4[-1]["close"]))
    return {"M15": frames_m15, "H1": h1, "H4": h4}


def bullish_choch(sweep: bool = True) -> dict[str, list[dict]]:
    """A FALLING M15 structure (bearish), then a bullish CHoCH back in the H4 direction.
    sweep=True: the leg-origin candle wicks below the last swing low (101.4) and closes back
    above it (a sell-side liquidity sweep). sweep=False: the origin low stays above it."""
    legs = []
    for _ in range(13):                         # -4 / +2.5: lower highs and lower lows
        legs += [(6, -4.0), (6, 2.5)]
    m15 = zigzag(160.0, legs, M15_SECONDS, START)
    shift = 104.0 - m15[-1]["close"]            # last swing high 104.1, last swing low 101.4
    m15 = [{**b, **{k: b[k] + shift for k in ("open", "high", "low", "close")}} for b in m15]
    t = m15[-1]["time"] + M15_SECONDS
    tail = [
        (104.0, 104.0, 103.0, 103.1),
        (103.1, 103.1, 102.2, 102.3),
        (102.3, 102.4, 100.8 if sweep else 101.6, 101.9),   # origin + order block (bearish)
        (101.9, 103.6, 101.8, 103.5),                        # displacement 1
        (103.5, 105.1, 103.4, 105.0),                        # closes above 104.1 -> CHoCH
        (105.0, 106.2, 104.8, 106.0),                        # FVG: 104.8 > 103.6
        (106.0, 106.1, 104.0, 104.2),                        # retrace
        (104.2, 104.3, 102.2, 102.6),                        # first tap of the order block [100.8, 102.4]
        (102.9, 103.6, 102.0, 103.5),                        # reaction: wick 0.9 of 1.6, closes above 102.4
    ]
    for open_, high, low, close in tail:
        m15.append(_bar(t, open_, high, low, close))
        t += M15_SECONDS
    last = m15[-1]["close"]
    m15.append(_bar(t, last, last, last, last))
    return _htf(m15)


def bearish(frames: dict[str, list[dict]], pivot: float = 200.0) -> dict[str, list[dict]]:
    """Mirror every price around `pivot` (a bullish setup becomes the bearish one)."""
    flip = lambda b: {"time": b["time"], "open": pivot - b["open"], "high": pivot - b["low"],  # noqa: E731
                      "low": pivot - b["high"], "close": pivot - b["close"]}
    return {tf: [flip(b) for b in bars] for tf, bars in frames.items()}
