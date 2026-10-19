"""T-033 implementations of library strategies (research only; never imported by the engine).

Every generator decides from closed bars (or, for stop-entry orders, from a level fixed before the
session) and returns lab signals: entry on an M15 bar at a realistic price (next open, or the stop
level / gap open for stop orders, BUY at the ask, SELL at the bid). Within the trigger bar the
simulator treats a touched stop pessimistically. Sources and rationale: research/library.py.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from research import experiments as ex
from research import lab, v6

NEW_YORK, FRANKFURT = ZoneInfo("America/New_York"), ZoneInfo("Europe/Berlin")
INDICES = {"NAS100": NEW_YORK, "US500": NEW_YORK, "GER40": FRANKFURT}
SESSION = {NEW_YORK: ((9, 30), (16, 0)), FRANKFURT: ((9, 0), (17, 30))}


def make(h, i15: int, family: str, long: bool, entry: float, stop: float, target: float | None,
         trail: float | None, max_bars: int, evidence: dict[str, Any] | None = None) -> dict[str, Any] | None:
    risk = (entry - stop) if long else (stop - entry)
    if not risk or risk <= 0 or (target is not None and ((target <= entry) if long else (target >= entry))):
        return None
    bar = h.full["M15"][i15]
    return {"index": i15, "utc": bar["utc"], "symbol": h.symbol, "strategy_id": family,
            "direction": "LONG" if long else "SHORT", "entry": entry, "stop_loss": stop, "take_profit": target,
            "trail": trail, "max_bars": max(1, max_bars), "spread": bar["spread"], "evidence": {"score": None, **(evidence or {})}}


def open_entry(h, i15: int, long: bool) -> float:
    bar = h.full["M15"][i15]
    return bar["open"] + bar["spread"] if long else bar["open"]


_LOCAL: dict[tuple[str, str], list[datetime]] = {}


def local_times(h, zone: ZoneInfo) -> list[datetime]:
    key = (h.symbol, str(zone))
    if key not in _LOCAL:
        _LOCAL[key] = [datetime.fromtimestamp(b["utc"], v6.UTC).astimezone(zone) for b in h.full["M15"]]
    return _LOCAL[key]


def _h1_atr_at(h, i15: int) -> float | None:
    """ATR(14) of H1 bars closed before M15 bar i15 opens."""
    c = v6.h1_context(h)
    times = [b["utc"] for b in c["bars"]] if "utc_list" not in c else c["utc_list"]
    c["utc_list"] = times
    j = bisect.bisect_right(times, h.full["M15"][i15]["utc"] - 3600) - 1
    return c["atr"][j] if j >= 0 else None


def _stop_entry(h, start: int, end: int, long: bool, level: float) -> tuple[int, float] | None:
    """First M15 bar in [start, end) whose ask (BUY) / bid (SELL) reaches `level`; fill at the level,
    or at the open when the bar opens beyond it (gap)."""
    m15 = h.full["M15"]
    for k in range(start, min(end, len(m15))):
        b = m15[k]
        if long:
            if b["open"] + b["spread"] >= level:
                return k, b["open"] + b["spread"]
            if b["high"] + b["spread"] >= level:
                return k, level
        else:
            if b["open"] <= level:
                return k, b["open"]
            if b["low"] <= level:
                return k, level
    return None


def _days(h) -> list[tuple[int, int]]:
    """[(first M15 index, end index)] per D1 bar (broker day), via the D1 open times."""
    c = v6.tf_context(h, "D1")
    m15_utc = [b["utc"] for b in h.full["M15"]]
    out = []
    for b in c["bars"]:
        s, e = bisect.bisect_left(m15_utc, b["utc"]), bisect.bisect_left(m15_utc, b["utc"] + 86400)
        out.append((s, e))
    return out


# ----- supertrend ------------------------------------------------------------------------------------

def supertrend(h, timeframe: str, k: float, n: int = 10) -> list[dict[str, Any]]:
    """Enter on a Supertrend flip (close crossing the active ATR band), initial stop and trail k x ATR."""
    c = v6.tf_context(h, timeframe) if timeframe != "H1" else {**v6.h1_context(h), "seconds": 3600}
    bars, atr = c["bars"], v6._atr(c["bars"], n)
    out, trend, upper, lower = [], None, None, None
    for i in range(n + 1, len(bars)):
        a = atr[i]
        if not a:
            continue
        mid = (bars[i]["high"] + bars[i]["low"]) / 2
        up, lo = mid + k * a, mid - k * a
        close, prev_close = bars[i]["close"], bars[i - 1]["close"]
        upper = up if upper is None or up < upper or prev_close > upper else upper
        lower = lo if lower is None or lo > lower or prev_close < lower else lower
        new = "UP" if close > upper else "DOWN" if close < lower else trend
        if trend is not None and new != trend:
            j = c["entry_index"][i]
            if j is not None:
                long = new == "UP"
                entry = open_entry(h, j, long)
                s = make(h, j, "supertrend", long, entry, entry - k * a if long else entry + k * a, None, k * a, 20 * 96)
                if s:
                    out.append(s)
        trend = new
    return out


# ----- intraday momentum (indices) ---------------------------------------------------------------------

def intraday_momentum(h, variant: str, stop_atr: float) -> list[dict[str, Any]]:
    """Gao et al. (2018): the session's early return predicts its last part.
    'gao': return from the previous session close to open+30min predicts the last 30 minutes.
    'late': return from the session open to 1h before the close predicts the last hour."""
    zone = INDICES.get(h.symbol)
    if zone is None:
        return []
    (oh, om), (ch, cm) = SESSION[zone]
    local = local_times(h, zone)
    m15 = h.full["M15"]
    by_day: dict[Any, dict[tuple[int, int], int]] = {}
    for i, t in enumerate(local):
        by_day.setdefault(t.date(), {})[(t.hour, t.minute)] = i
    days = sorted(by_day)
    out = []
    close_minutes = ch * 60 + cm
    for d_prev, d in zip(days, days[1:]):
        today, prev = by_day[d], by_day[d_prev]
        last_minutes = 30 if variant == "gao" else 60
        entry_hm = divmod(close_minutes - last_minutes, 60)
        prev_close_hm = divmod(close_minutes - 15, 60)                 # last bar of the previous session
        if variant == "gao":
            ref_i, sig_i = prev.get(prev_close_hm), today.get(divmod(oh * 60 + om + 30, 60))
            ref = m15[ref_i]["close"] if ref_i is not None else None
        else:
            ref_i, sig_i = today.get((oh, om)), today.get(entry_hm)
            ref = m15[ref_i]["open"] if ref_i is not None else None
        j = today.get(entry_hm)
        if ref is None or sig_i is None or j is None:
            continue
        signal_price = m15[sig_i]["open"] if variant == "late" else m15[sig_i]["open"]
        move = signal_price - ref
        a = _h1_atr_at(h, j)
        if not a or move == 0:
            continue
        long = move > 0
        entry = open_entry(h, j, long)
        s = make(h, j, f"intraday_momentum_{variant}", long, entry, entry - stop_atr * a if long else entry + stop_atr * a,
                 None, None, last_minutes // 15, {"move": move})
        if s:
            s["take_profit"] = entry + 50 * stop_atr * a if long else entry - 50 * stop_atr * a   # time exit
            out.append(s)
    return out


# ----- RSI(2) -----------------------------------------------------------------------------------------

def _rsi(closes: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    gains = losses = 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g, l = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            gains += g / n
            losses += l / n
        else:
            gains = (gains * (n - 1) + g) / n
            losses = (losses * (n - 1) + l) / n
        if i >= n:
            out[i] = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    return out


def rsi2(h, timeframe: str, stop_atr: float) -> list[dict[str, Any]]:
    """Connors RSI(2): with the trend (close vs SMA200), buy RSI(2) < 10 / sell RSI(2) > 90; target the
    SMA5 level at entry (the 'close above SMA5' exit), stop k x ATR, at most 5 bars."""
    c = v6.tf_context(h, timeframe) if timeframe != "H1" else v6.h1_context(h)
    bars, atr = c["bars"], c["atr"]
    closes = [b["close"] for b in bars]
    rsi = _rsi(closes, 2)
    seconds = 86400 if timeframe == "D1" else 3600
    out = []
    for i in range(200, len(bars)):
        j, a = c["entry_index"][i], atr[i]
        if j is None or not a or rsi[i] is None:
            continue
        sma200, sma5 = sum(closes[i - 199:i + 1]) / 200, sum(closes[i - 4:i + 1]) / 5
        long = closes[i] > sma200 and rsi[i] < 10
        short = closes[i] < sma200 and rsi[i] > 90
        if not (long or short):
            continue
        entry = open_entry(h, j, long)
        s = make(h, j, f"rsi2_{timeframe}", long, entry, entry - stop_atr * a if long else entry + stop_atr * a,
                 sma5, None, 5 * seconds // 900)
        if s:
            out.append(s)
    return out


# ----- NR7 and volatility breakout (stop entries) ------------------------------------------------------

def nr7(h, stop_mode: str, exit_: str) -> list[dict[str, Any]]:
    """After a D1 NR7 day, a stop order beyond its high (BUY) / low (SELL) the next day; first touch
    wins; stop at the opposite side ('far') or the middle ('mid'); exit at the day's end or at 2R."""
    c = v6.tf_context(h, "D1")
    bars, days = c["bars"], _days(h)
    out = []
    for i in range(7, len(bars) - 1):
        ranges = [b["high"] - b["low"] for b in bars[i - 6:i + 1]]
        if ranges[-1] > min(ranges) or ranges[-1] <= 0:
            continue
        s15, e15 = days[i + 1]
        hi, lo = bars[i]["high"], bars[i]["low"]
        long_fill, short_fill = _stop_entry(h, s15, e15, True, hi), _stop_entry(h, s15, e15, False, lo)
        fills = [f for f in ((long_fill, True), (short_fill, False)) if f[0]]
        if not fills:
            continue
        (k, price), long = min(fills, key=lambda f: f[0][0])
        stop = (lo if long else hi) if stop_mode == "far" else (hi + lo) / 2
        risk = (price - stop) if long else (stop - price)
        target = (price + 2 * risk if long else price - 2 * risk) if exit_ == "2R" else (price + 50 * risk if long else price - 50 * risk)
        s = make(h, k, "nr7", long, price, stop, target, None, e15 - k)
        if s:
            out.append(s)
    return out


def volatility_breakout(h, k: float, trend_filter: bool) -> list[dict[str, Any]]:
    """Williams: stop orders at today's open +- k x yesterday's range; stop at the open; exit at day end."""
    c = v6.tf_context(h, "D1")
    bars, days = c["bars"], _days(h)
    m15 = h.full["M15"]
    out = []
    for i in range(201, len(bars)):
        s15, e15 = days[i]
        if e15 - s15 < 8:
            continue
        rng = bars[i - 1]["high"] - bars[i - 1]["low"]
        day_open = m15[s15]["open"]
        up = c["ema50"][i - 1] > c["ema200"][i - 1]
        fills = []
        for long in (True, False):
            if trend_filter and up != long:
                continue
            f = _stop_entry(h, s15 + 1, e15, long, day_open + k * rng if long else day_open - k * rng)
            if f:
                fills.append((f, long))
        if not fills:
            continue
        (j, price), long = min(fills, key=lambda f: f[0][0])
        stop = day_open
        risk = (price - stop) if long else (stop - price)
        s = make(h, j, "vol_breakout", long, price, stop, price + 50 * risk if long else price - 50 * risk, None, e15 - j)
        if s:
            out.append(s)
    return out


# ----- FX local-hours seasonality ----------------------------------------------------------------------

LEGS = {  # (symbol, long?, start UTC hour, end UTC hour): a currency weakens in its own hours
    "eu": [("EURUSD", False, 7, 13), ("GBPUSD", False, 7, 13), ("USDCHF", True, 7, 13)],
    "us": [("EURUSD", True, 13, 20), ("GBPUSD", True, 13, 20), ("USDCHF", False, 13, 20), ("USDCAD", True, 13, 20)],
    "asia": [("USDJPY", True, 0, 7), ("AUDUSD", False, 0, 7), ("NZDUSD", False, 0, 7)],
}


def fx_local_hours(h, legs: str, stop_atr: float) -> list[dict[str, Any]]:
    """Breedon & Ranaldo (2013): hold each leg from its start to its end hour (UTC) on weekdays."""
    chosen = [leg for name in (["eu", "us", "asia"] if legs == "all" else [legs]) for leg in LEGS[name] if leg[0] == h.symbol]
    if not chosen:
        return []
    m15 = h.full["M15"]
    out = []
    for i, b in enumerate(m15):
        t = datetime.fromtimestamp(b["utc"], v6.UTC)
        if t.minute or t.weekday() >= 5:
            continue
        for _, long, start, end in chosen:
            if t.hour == start:
                a = _h1_atr_at(h, i)
                if not a:
                    continue
                entry = open_entry(h, i, long)
                s = make(h, i, f"fx_hours_{legs}", long, entry, entry - stop_atr * a if long else entry + stop_atr * a,
                         entry + 50 * stop_atr * a if long else entry - 50 * stop_atr * a, None, (end - start) * 4)
                if s:
                    out.append(s)
    return out


# ----- calendar: turn of month, overnight drift ---------------------------------------------------------

def turn_of_month(h, stop_atr: float) -> list[dict[str, Any]]:
    """Long indices from the open of the month's last trading day to the close of the 3rd trading day."""
    if h.symbol not in INDICES:
        return []
    c = v6.tf_context(h, "D1")
    bars, days = c["bars"], _days(h)
    months = [datetime.fromtimestamp(b["utc"] + 43200, v6.UTC).strftime("%Y-%m") for b in bars]
    out = []
    for i in range(201, len(bars) - 4):
        if months[i] == months[i + 1] or not c["atr"][i - 1]:
            continue
        s15 = days[i][0]
        e15 = days[i + 3][1]
        if s15 >= len(h.full["M15"]) or e15 <= s15:
            continue
        entry = open_entry(h, s15, True)
        a = c["atr"][i - 1]
        s = make(h, s15, "turn_of_month", True, entry, entry - stop_atr * a, entry + 50 * stop_atr * a, None, e15 - s15)
        if s:
            out.append(s)
    return out


def overnight_drift(h, stop_atr: float) -> list[dict[str, Any]]:
    """Long US indices from the cash close (16:00 New York) to the next cash open (09:30)."""
    if INDICES.get(h.symbol) is not NEW_YORK:
        return []
    local = local_times(h, NEW_YORK)
    out = []
    for i, t in enumerate(local):
        if (t.hour, t.minute) != (16, 0) or t.weekday() >= 5:
            continue
        end = next((k for k in range(i + 1, min(len(local), i + 400)) if (local[k].hour, local[k].minute) == (9, 30)), None)
        a = _h1_atr_at(h, i)
        if end is None or not a:
            continue
        entry = open_entry(h, i, True)
        s = make(h, i, "overnight", True, entry, entry - stop_atr * a, entry + 50 * stop_atr * a, None, end - i)
        if s:
            out.append(s)
    return out


# ----- volume climax --------------------------------------------------------------------------------

def volume_climax(h, multiple: float, target_r: float) -> list[dict[str, Any]]:
    """H1 tick volume > multiple x its 50-bar median with a rejection wick (> 60% of the range against
    the bar's extreme) -> fade; stop beyond the extreme + 0.5 ATR; target fixed R; 24h time exit."""
    c = v6.h1_context(h)
    bars, atr = c["bars"], c["atr"]
    out = []
    for i in range(60, len(bars)):
        j, a, b = c["entry_index"][i], atr[i], bars[i]
        rng = b["high"] - b["low"]
        if j is None or not a or rng <= 0:
            continue
        vols = sorted(x["tick_volume"] for x in bars[i - 50:i])
        if not vols or b["tick_volume"] < multiple * vols[25]:
            continue
        upper_wick = (b["high"] - max(b["open"], b["close"])) / rng
        lower_wick = (min(b["open"], b["close"]) - b["low"]) / rng
        if upper_wick > 0.6:
            long, stop = False, b["high"] + 0.5 * a
        elif lower_wick > 0.6:
            long, stop = True, b["low"] - 0.5 * a
        else:
            continue
        entry = open_entry(h, j, long)
        risk = (entry - stop) if long else (stop - entry)
        s = make(h, j, "volume_climax", long, entry, stop, entry + target_r * risk if long else entry - target_r * risk, None, 96)
        if s:
            out.append(s)
    return out


# ----- machine learning: walk-forward L2 logistic classifier ---------------------------------------------

FEATURES = ("r1", "r3", "r6", "r24", "d_ema20", "d_ema50", "d_ema200", "atr_ratio", "body", "upper_wick",
            "lower_wick", "vol_ratio", "rsi14", "hour_sin", "hour_cos", "dow")
HORIZON = 24


def ml_rows(h) -> list[dict[str, Any]]:
    """One row per closed H1 bar: features from bars <= i, label = +1 ATR reached before -1 ATR within
    HORIZON bars (1), the reverse (0), or neither/both-in-one-bar (None)."""
    c = v6.h1_context(h)
    bars, atr = c["bars"], c["atr"]
    closes = [b["close"] for b in bars]
    rsi = _rsi(closes, 14)
    rows = []
    for i in range(210, len(bars) - 1):
        a = atr[i]
        if not a or rsi[i] is None or c["entry_index"][i] is None:
            continue
        b = bars[i]
        rng = max(b["high"] - b["low"], 1e-12)
        vols = sorted(x["tick_volume"] for x in bars[i - 50:i])
        t = datetime.fromtimestamp(b["utc"] + 3600, v6.UTC)
        f = {"r1": (closes[i] - closes[i - 1]) / a, "r3": (closes[i] - closes[i - 3]) / a, "r6": (closes[i] - closes[i - 6]) / a,
             "r24": (closes[i] - closes[i - 24]) / a, "d_ema20": (closes[i] - c["ema20"][i]) / a,
             "d_ema50": (closes[i] - c["ema50"][i]) / a, "d_ema200": (closes[i] - c["ema200"][i]) / a,
             "atr_ratio": a / (sorted(x for x in atr[i - 100:i] if x)[len([x for x in atr[i - 100:i] if x]) // 2] or a),
             "body": (b["close"] - b["open"]) / rng, "upper_wick": (b["high"] - max(b["open"], b["close"])) / rng,
             "lower_wick": (min(b["open"], b["close"]) - b["low"]) / rng,
             "vol_ratio": b["tick_volume"] / (vols[25] or 1), "rsi14": (rsi[i] - 50) / 50,
             "hour_sin": math.sin(2 * math.pi * t.hour / 24), "hour_cos": math.cos(2 * math.pi * t.hour / 24),
             "dow": t.weekday() / 4.0}
        label = None
        up, down = closes[i] + a, closes[i] - a
        for k in range(i + 1, min(len(bars), i + 1 + HORIZON)):
            hit_up, hit_down = bars[k]["high"] >= up, bars[k]["low"] <= down
            if hit_up and hit_down:
                break
            if hit_up or hit_down:
                label = 1 if hit_up else 0
                break
        label_end = bars[min(len(bars) - 1, i + HORIZON)]["utc"] + 3600
        rows.append({"i": i, "utc": b["utc"] + 3600, "label_end": label_end, "x": [f[k] for k in FEATURES], "y": label,
                     "atr": a, "j": c["entry_index"][i]})
    return rows


def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    from scipy.optimize import minimize
    Xb = np.hstack([X, np.ones((len(X), 1))])

    def loss(w):
        z = Xb @ w
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        eps = 1e-9
        reg = 0.5 * l2 * np.sum(w[:-1] ** 2) / len(X)
        return -np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)) + reg, Xb.T @ (p - y) / len(X) + np.r_[l2 * w[:-1] / len(X), 0.0]

    res = minimize(loss, np.zeros(Xb.shape[1]), jac=True, method="L-BFGS-B")
    return res.x


class LogitModel:
    """Pooled across instruments; trained ONLY on rows whose label window ends before TRAIN end (purged)."""

    def __init__(self) -> None:
        self.rows = {s: ml_rows(lab.history_for(s)) for s in lab.SYMBOLS}
        end = v6.TRAIN[1].timestamp()
        train = [r for rows in self.rows.values() for r in rows if r["y"] is not None and r["label_end"] < end
                 and r["utc"] >= v6.TRAIN[0].timestamp()]
        X = np.array([r["x"] for r in train])
        self.mu, self.sd = X.mean(axis=0), X.std(axis=0) + 1e-9
        self.w = fit_logit((X - self.mu) / self.sd, np.array([r["y"] for r in train], dtype=float))
        self.train_size = len(train)
        self.train_accuracy = float(np.mean(((self.predict(X) > 0.5).astype(int)) == np.array([r["y"] for r in train])))

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = (np.asarray(X) - self.mu) / self.sd
        return 1 / (1 + np.exp(-(np.hstack([Z, np.ones((len(Z), 1))]) @ self.w)))

    def signals(self, threshold: float) -> list[dict[str, Any]]:
        out = []
        for symbol, rows in self.rows.items():
            if not rows:
                continue
            h = lab.history_for(symbol)
            p = self.predict(np.array([r["x"] for r in rows]))
            for r, prob in zip(rows, p):
                if prob > threshold or prob < 1 - threshold:
                    long = prob > threshold
                    entry = open_entry(h, r["j"], long)
                    a = r["atr"]
                    s = make(h, r["j"], "ml_logit", long, entry, entry - a if long else entry + a,
                             entry + a if long else entry - a, None, HORIZON * 4, {"p": float(prob)})
                    if s:
                        out.append(s)
        return sorted(out, key=lambda s: (s["utc"], s["symbol"]))


@lru_cache(maxsize=1)
def logit_model() -> LogitModel:
    return LogitModel()
