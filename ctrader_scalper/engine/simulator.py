"""Cost-aware execution and portfolio risk simulator.

Fill model (M1 bid bars, spread added for the ask side):
* Entry: market order at the open of the first M1 bar at/after the decision
  time, long at ask (+ slippage), short at bid (- slippage).
* Stop: triggered on the side that closes the trade (bid for longs, ask for
  shorts); gaps through the stop fill at the bar open; slippage added.
* Target: limit, no slippage. If stop and target sit inside the same M1 bar
  the STOP is assumed first (conservative).
* Time stop: market exit at the open after `max_hold_min`, with slippage.
* Commission: notional x rate on entry and exit.

Portfolio rules mirror the cBot: 0.5% equity risk, max 2 open positions,
one per symbol, 3% daily loss stop that counts open risk, halt for the day
after 3 consecutive losses, cooldown of 3 M5 bars per symbol after an exit.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np
import pandas as pd

from .market import INSTRUMENTS, Instrument


@dataclass(frozen=True)
class TradeParams:
    rr: float = 1.5
    sl_buffer_atr: float = 0.3
    min_score: int = 80
    setups: tuple = ("BRT", "PB")
    breakeven_r: float = 0.0          # 0 = off
    max_hold_min: int = 120
    min_sl_atr: float = 0.5
    max_sl_atr: float = 3.0
    max_cost_to_risk: float = 0.25


@dataclass(frozen=True)
class RiskParams:
    start_equity: float = 10_000.0
    risk_pct: float = 0.5
    max_positions: int = 2
    max_daily_loss_pct: float = 3.0
    max_consecutive_losses: int = 3
    cooldown_min: int = 15


class M1Path:
    def __init__(self, m1: pd.DataFrame):
        self.t = m1["time"].to_numpy()
        self.o = m1["open"].to_numpy(float)
        self.h = m1["high"].to_numpy(float)
        self.l = m1["low"].to_numpy(float)
        self.s = m1["spread_px"].to_numpy(float)


def plan_trade(c, p: TradeParams, inst: Instrument):
    """Stop/target from the candidate; None if it fails the cost/geometry rules."""
    if c.setup not in p.setups or c.score < p.min_score:
        return None
    side = c.side
    stop = c.anchor - side * p.sl_buffer_atr * c.atr
    est_entry = c.ref + (c.spread if side > 0 else 0.0)
    risk = (est_entry - stop) * side
    if risk <= 0 or risk < p.min_sl_atr * c.atr or risk > p.max_sl_atr * c.atr:
        return None
    cost = c.spread + 2 * inst.slippage + 2 * inst.commission_rate * est_entry
    if cost / risk > p.max_cost_to_risk:
        return None
    return stop, risk


def simulate_exit(path: M1Path, k: int, side: int, stop: float, risk_hint: float,
                  p: TradeParams, inst: Instrument):
    """Return dict with entry/exit prices, times and reason, starting at M1 index k."""
    n = len(path.t)
    if k >= n:
        return None
    entry = path.o[k] + (path.s[k] + inst.slippage if side > 0 else -inst.slippage)
    risk = (entry - stop) * side
    if risk <= 0:
        return None
    target = entry + side * p.rr * risk
    end_time = path.t[k] + np.timedelta64(p.max_hold_min, "m")
    k_end = int(np.searchsorted(path.t, end_time, side="left"))
    seg = slice(k, min(k_end, n))
    h, l, o, s = path.h[seg], path.l[seg], path.o[seg], path.s[seg]
    # price on the closing side: bid for longs, ask (= bid + spread) for shorts
    adv = l if side > 0 else h + s          # adverse extreme
    fav = h if side > 0 else l + s          # favourable extreme
    opn = o if side > 0 else o + s

    def first(mask):
        idx = np.flatnonzero(mask)
        return int(idx[0]) if len(idx) else None

    stop_cur = stop
    be_from = None
    if p.breakeven_r > 0:
        trig = first((fav - entry) * side >= p.breakeven_r * risk)
        if trig is not None:
            be_from = trig + 1  # move the stop from the next bar
    hit_stop0 = first((adv - stop) * side <= 0)
    hit_tp = first((fav - target) * side >= 0)
    hit_be = None
    if be_from is not None and be_from < len(adv):
        be_px = entry + side * (s[0] + 2 * inst.commission_rate * entry)  # cover costs
        m = (adv[be_from:] - be_px) * side <= 0
        idx = first(m)
        hit_be = None if idx is None else be_from + idx
    # earliest event; stop wins ties
    events = []
    if hit_stop0 is not None and (be_from is None or hit_stop0 < be_from):
        events.append((hit_stop0, 0, "stop", stop))
    if hit_be is not None:
        events.append((hit_be, 0, "breakeven", entry + side * (s[0] + 2 * inst.commission_rate * entry)))
    if hit_tp is not None:
        events.append((hit_tp, 1, "target", target))
    if events:
        j, _, reason, level = min(events)
        if reason == "target":
            px = level
        else:
            gap_open = opn[j]
            px = (min(level, gap_open) if side > 0 else max(level, gap_open)) - side * inst.slippage
        exit_k = k + j
    else:
        exit_k = min(k_end, n - 1)
        reason = "time" if k_end < n else "data_end"
        px = (path.o[exit_k] if side > 0 else path.o[exit_k] + path.s[exit_k]) - side * inst.slippage
    return {"entry": entry, "exit": px, "stop": stop, "target": target, "risk_px": risk,
            "entry_time": path.t[k], "exit_time": path.t[exit_k], "reason": reason}


def build_trades(cands: pd.DataFrame, path: M1Path, p: TradeParams, inst: Instrument) -> list[dict]:
    """Every candidate that would be taken if the portfolio allowed it."""
    out = []
    if cands.empty:
        return out
    ks = np.searchsorted(path.t, cands["time"].to_numpy(), side="left")
    for c, k in zip(cands.itertuples(index=False), ks):
        plan = plan_trade(c, p, inst)
        if plan is None:
            continue
        stop, risk_hint = plan
        # no fill if the next bar is far away (market closed / data gap)
        if k >= len(path.t) or path.t[k] - c.time > np.timedelta64(10, "m"):
            continue
        ex = simulate_exit(path, int(k), c.side, stop, risk_hint, p, inst)
        if ex is None:
            continue
        ex.update({"symbol": c.symbol, "side": c.side, "setup": c.setup, "score": c.score,
                   "session": c.session, "signal_time": c.time})
        out.append(ex)
    return out


def run_portfolio(trades: list[dict], r: RiskParams, insts=INSTRUMENTS) -> pd.DataFrame:
    """Apply sizing and account-level risk gates chronologically."""
    trades = sorted(trades, key=lambda t: (t["entry_time"], t["symbol"]))
    equity = r.start_equity
    open_pos: list[dict] = []
    taken = []
    day = None
    day_start = equity
    day_realized = 0.0
    consec = 0
    halted = False
    last_exit = {}

    def close_until(t):
        nonlocal equity, day_realized, consec
        for pos in sorted([x for x in open_pos if x["exit_time"] <= t], key=lambda x: x["exit_time"]):
            open_pos.remove(pos)
            equity += pos["pnl"]
            if pd.Timestamp(pos["exit_time"]).normalize() == day:
                day_realized += pos["pnl"]
                consec = consec + 1 if pos["pnl"] < 0 else 0
            last_exit[pos["symbol"]] = pos["exit_time"]

    for t in trades:
        now = t["entry_time"]
        d = pd.Timestamp(now).normalize()
        if d != day:
            close_until(d.to_datetime64())
            day, day_start, day_realized, consec, halted = d, equity, 0.0, 0, False
        close_until(now)
        if halted or consec >= r.max_consecutive_losses or day_realized <= -r.max_daily_loss_pct / 100 * day_start:
            halted = True
            continue
        if len(open_pos) >= r.max_positions or any(p["symbol"] == t["symbol"] for p in open_pos):
            continue
        le = last_exit.get(t["symbol"])
        if le is not None and now - le < np.timedelta64(r.cooldown_min, "m"):
            continue
        inst = insts[t["symbol"]]
        risk_cash = equity * r.risk_pct / 100
        units = np.floor(risk_cash / t["risk_px"] / inst.volume_step) * inst.volume_step
        if units < inst.volume_min:
            continue
        cash_risk = units * t["risk_px"]
        open_risk = sum(p["cash_risk"] for p in open_pos)
        if -day_realized + open_risk + cash_risk > r.max_daily_loss_pct / 100 * day_start:
            continue
        gross = (t["exit"] - t["entry"]) * t["side"] * units
        comm = inst.commission_rate * units * (t["entry"] + t["exit"])
        pos = dict(t, units=units, cash_risk=cash_risk, gross=gross, commission=comm,
                   pnl=gross - comm, r_multiple=(gross - comm) / cash_risk, equity_before=equity)
        open_pos.append(pos)
        taken.append(pos)
    close_until(np.datetime64("2262-01-01"))
    return pd.DataFrame(taken)


def params_dict(p) -> dict:
    d = asdict(p)
    if "setups" in d:
        d["setups"] = list(d["setups"])
    return d
