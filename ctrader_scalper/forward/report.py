"""Forward experiment fwd-xau-001: daily report + broker-vs-simulation reconciliation.

    cd ctrader_scalper
    python -m forward.report                 # yesterday and today (UTC), cumulative section included
    python -m forward.report --date 2026-11-24
    python -m forward.report --no-mt5        # skip the MT5 data refresh / reconciliation

Reads only the cBot journal (RealTime records of experiment fwd-xau-001). Never places, modifies or closes orders.
Reconciliation (needs a running MT5 terminal on the same IC Markets feed family):
  1. signal parity  - candidates the Python reference engine finds on MT5 M1 data vs signals the cBot journaled;
  2. fill model     - each real trade replayed by the simulator with the same entry minute, stop and target;
  3. cost model     - real spread / slippage / commission vs the simulator's assumptions.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from engine.market import INSTRUMENTS, broker_to_utc
from engine.simulator import M1Path, TradeParams, simulate_exit
from engine.strategy import generate_candidates

EXPERIMENT = "fwd-xau-001"
SYMBOL = "XAUUSD"
HERE = Path(__file__).resolve().parent
OUT = HERE / "reports"
DATA = HERE / "data"


def journal_dir() -> Path | None:
    import os
    env = os.getenv("SCALPER_JOURNAL_DIR")
    for c in ([Path(env)] if env else []) + [Path.home() / "OneDrive" / "Documents" / "TradeDenScalper" / "journal",
                                             Path.home() / "Documents" / "TradeDenScalper" / "journal"]:
        if c.is_dir():
            return c
    return None


def load_events(folder: Path | None) -> pd.DataFrame:
    rows = []
    if folder:
        for f in sorted(folder.glob("journal-*.jsonl")):
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("running_mode") == "RealTime" and r.get("experiment_id") == EXPERIMENT:
                    rows.append(r)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["t"] = pd.to_datetime(df["ts"].str.replace("Z", ""), errors="coerce")
        df = df.dropna(subset=["t"]).sort_values("t").reset_index(drop=True)
    return df


def stats(closes: pd.DataFrame) -> dict:
    if closes.empty or "net" not in closes:
        return {"trades": 0}
    net = closes["net"].astype(float).to_numpy()
    r = closes["r_multiple"].astype(float).to_numpy() if "r_multiple" in closes else np.array([])
    wins, losses = net[net > 0], net[net <= 0]
    out = {"trades": int(len(net)), "net": round(float(net.sum()), 2), "win_rate": round(len(wins) / len(net) * 100, 1),
           "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.sum() < 0 else None,
           "avg_win": round(float(wins.mean()), 2) if len(wins) else None, "avg_loss": round(float(losses.mean()), 2) if len(losses) else None,
           "commission": round(float(closes.get("commission", pd.Series(dtype=float)).astype(float).sum()), 2),
           "swap": round(float(closes.get("swap", pd.Series(dtype=float)).fillna(0).astype(float).sum()), 2)}
    if len(r):
        out["expectancy_r"] = round(float(np.nanmean(r)), 3)
        if len(r) > 2 and np.nanstd(r, ddof=1) > 0:
            se = np.nanstd(r, ddof=1) / math.sqrt(len(r))
            out["ci95_r"] = [round(float(np.nanmean(r) - 1.96 * se), 3), round(float(np.nanmean(r) + 1.96 * se), 3)]
    if "balance_after" in closes:
        b = closes["balance_after"].astype(float).to_numpy()
        start = b[0] - net[0]
        peak = np.maximum.accumulate(np.r_[start, b])
        out["max_drawdown_pct"] = round(float(((peak - np.r_[start, b]) / peak).max() * 100), 2)
    return out


def refresh_mt5_m1(days: int = 10) -> pd.DataFrame | None:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    mt5.symbol_select(SYMBOL, True)
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, min(99_999, days * 1440))
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    df["time"] = broker_to_utc(pd.to_datetime(df["time"], unit="s"))
    df = df.dropna(subset=["time"]).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    inst = INSTRUMENTS[SYMBOL]
    df["spread_px"] = np.maximum(df["spread"].astype(float) * inst.point, inst.spread_floor)
    DATA.mkdir(exist_ok=True)
    df.to_csv(DATA / f"{SYMBOL}_M1_forward.csv.gz", index=False)
    return df[["time", "open", "high", "low", "close", "spread_px"]]


def reconcile(day_start, day_end, signals: pd.DataFrame, opened: pd.DataFrame, closes: pd.DataFrame, m1: pd.DataFrame | None) -> dict:
    if m1 is None or m1.empty:
        return {"available": False, "reason": "MT5 terminal not reachable; reconciliation skipped"}
    out = {"available": True}
    # 1. signal parity (cBot signals on the cTrader feed vs reference engine on the MT5 feed)
    cands = generate_candidates(SYMBOL, m1)
    ref = cands[(cands["time"] >= day_start) & (cands["time"] < day_end)]
    bot = signals.copy()
    if not bot.empty:
        bot["bar_close"] = pd.to_datetime(bot["bar_close_utc"].str.replace("Z", ""))
        bot["side_n"] = np.where(bot["side"] == "buy", 1, -1)
    ref_keys = {(t, s, st) for t, s, st in zip(ref["time"], ref["side"], ref["setup"])}
    bot_keys = {(t, s, st) for t, s, st in zip(bot.get("bar_close", []), bot.get("side_n", []), bot.get("setup", []))}
    both = ref_keys & bot_keys
    out["signal_parity"] = {"reference_candidates": len(ref_keys), "cbot_signals": len(bot_keys), "matched": len(both),
                            "only_reference": len(ref_keys - bot_keys), "only_cbot": len(bot_keys - ref_keys),
                            "note": "differences come from the two price feeds (cTrader vs MT5) and from bars missing around restarts"}
    # 2. fill model: replay each real trade
    path, inst = M1Path(m1), INSTRUMENTS[SYMBOL]
    rows = []
    for c in closes.itertuples():
        o = opened[opened["position_id"] == c.position_id]
        if o.empty or pd.isna(getattr(c, "planned_stop", np.nan)):
            continue
        o = o.iloc[0]
        side = 1 if o["side"] == "buy" else -1
        entry_t = pd.to_datetime(str(o["entry_time"]).replace("Z", "")).floor("min")
        k = int(np.searchsorted(path.t, np.datetime64(entry_t), side="left"))
        if k >= len(path.t):
            continue
        risk = abs(float(o["entry"]) - float(o["stop"]))
        rr = abs(float(o["target"]) - float(o["entry"])) / risk if risk > 0 and not pd.isna(o["target"]) else 1.5
        sim = simulate_exit(path, k, side, float(o["stop"]), risk, TradeParams(rr=rr, max_hold_min=120), inst)
        if sim is None:
            continue
        actual_r = float(c.r_multiple) if not pd.isna(c.r_multiple) else np.nan
        sim_gross_r = (sim["exit"] - sim["entry"]) * side / sim["risk_px"]
        sim_comm_r = inst.commission_rate * (sim["entry"] + sim["exit"]) / sim["risk_px"]
        rows.append({"position_id": c.position_id, "actual_reason": c.reason, "sim_reason": sim["reason"],
                     "actual_entry": float(o["entry"]), "sim_entry": round(sim["entry"], 3),
                     "actual_exit": float(c.exit), "sim_exit": round(sim["exit"], 3),
                     "actual_r": round(actual_r, 3), "sim_r": round(sim_gross_r - sim_comm_r, 3)})
    rec = pd.DataFrame(rows)
    out["fill_model"] = {"trades_compared": int(len(rec)),
                         "same_exit_reason": int((rec["actual_reason"].str.lower().str.replace("loss", "").str.replace("profit", "")
                                                  .map({"stop": "stop", "take": "target"}).fillna("time") == rec["sim_reason"]).sum()) if len(rec) else 0,
                         "mean_actual_r": round(float(rec["actual_r"].mean()), 3) if len(rec) else None,
                         "mean_sim_r": round(float(rec["sim_r"].mean()), 3) if len(rec) else None,
                         "rows": rec.to_dict("records")}
    return out


def cost_model(opened: pd.DataFrame, closes: pd.DataFrame) -> dict:
    inst = INSTRUMENTS[SYMBOL]
    out = {"assumed": {"spread_floor": inst.spread_floor, "slippage_per_fill": inst.slippage,
                       "commission_per_side_rate": inst.commission_rate}}
    if not opened.empty:
        out["actual_spread_at_signal_median"] = round(float(opened["spread"].astype(float).median()), 4)
        if "spread_at_fill" in opened:
            out["actual_spread_at_fill_median"] = round(float(opened["spread_at_fill"].astype(float).median()), 4)
        out["actual_entry_slippage_mean"] = round(float(opened["slippage"].astype(float).mean()), 4)
        out["actual_entry_slippage_max_adverse"] = round(float(opened["slippage"].astype(float).max()), 4)
        if "latency_ms" in opened:
            out["order_latency_ms_median"] = round(float(opened["latency_ms"].astype(float).median()), 1)
    if not closes.empty and "commission" in closes:
        notional = (closes["entry"].astype(float) + closes["exit"].astype(float)) * closes["units"].astype(float)
        out["actual_commission_rate_per_side"] = round(float((-closes["commission"].astype(float) / notional).mean()), 7)
        if "stop_slippage" in closes:
            ss = closes["stop_slippage"].dropna().astype(float)
            if len(ss):
                out["actual_stop_slippage_mean"] = round(float(ss.mean()), 4)
    return out


def build(day: datetime.date, events: pd.DataFrame, m1: pd.DataFrame | None) -> dict:
    d0 = pd.Timestamp(day)
    d1 = d0 + pd.Timedelta(days=1)
    ev = events[(events["t"] >= d0) & (events["t"] < d1)] if not events.empty else events
    get = lambda df, kind: df[df["event"] == kind] if not df.empty else df
    signals = get(ev, "signal")
    opened = signals[signals["decision"] == "opened"] if not signals.empty else signals
    closes = get(ev, "close").drop_duplicates(["run_id", "position_id"]) if not ev.empty else ev
    all_open = get(events, "signal")
    all_open = all_open[all_open["decision"] == "opened"] if not all_open.empty else all_open
    all_closes = get(events, "close").drop_duplicates(["run_id", "position_id"]) if not events.empty else events
    starts = get(events, "start")
    hb = get(ev, "heartbeat")
    rep = {
        "experiment": EXPERIMENT, "date_utc": str(day), "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": {
            "ever_started": bool(len(starts)),
            "last_start": None if starts.empty else {k: starts.iloc[-1].get(k) for k in ("ts", "execution_mode", "execution_gate", "demo_verified", "is_live", "account", "broker", "balance")},
            "live_ever_seen": bool(len(starts)) and bool(starts.get("is_live", pd.Series(dtype=bool)).fillna(False).astype(bool).any()),
            "heartbeats_today": int(len(hb)), "last_heartbeat": None if hb.empty else hb.iloc[-1]["ts"],
            "halted_now": None if hb.empty else bool(hb.iloc[-1].get("halted")),
            "halt_reason": None if hb.empty or pd.isna(hb.iloc[-1].get("halt_reason")) else hb.iloc[-1].get("halt_reason"),
        },
        "signals": {"total": int(len(signals)), "decisions": dict(Counter(signals["decision"])) if len(signals) else {},
                    "skip_reasons": dict(Counter(signals[signals["decision"] == "skipped"]["reason"])) if len(signals) else {}},
        "today": stats(closes), "cumulative": stats(all_closes),
        "risk_events": [] if ev.empty else ev[ev["event"].isin(["halt", "safety", "time_exit"])][["ts", "event"] + [c for c in ("reason", "message") if c in ev]].fillna("").to_dict("records"),
        "costs_today": cost_model(opened, closes), "costs_cumulative": cost_model(all_open, all_closes),
        "reconciliation": reconcile(d0, d1, signals, opened, closes, m1),
        "assessments": assessments(get(ev, "market_assessment")),
        "tradeden_copy": copy_stats(get(ev, "tradeden_signal")),
        "execution_test": [] if events.empty else get(events, "execution_test").drop(columns=["t"], errors="ignore").fillna("").to_dict("records"),
        "paper_trades_simulated": paper(get(ev, "paper_trade_open"), get(ev, "paper_trade_close"),
                                        get(events, "paper_trade_close")),
    }
    return rep


def copy_stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"received": 0}
    return {"received": int(len(t)), "by_source": dict(Counter(t.get("source", pd.Series(dtype=str)).fillna(""))),
            "decisions": dict(Counter(t["decision"].fillna(""))),
            "skip_reasons": dict(Counter(t[t["decision"] == "skipped"]["reason"].fillna(""))),
            "opened": t[t["decision"] == "opened"][[c for c in ("ts", "signal_id", "broker_symbol", "side", "entry", "stop", "target", "units", "risk_cash") if c in t]].fillna("").to_dict("records")}


def assessments(a: pd.DataFrame) -> dict:
    if a.empty:
        return {"count": 0}
    last = a.iloc[-1]
    keep = ("ts", "bid", "ask", "spread", "session", "m15_bias", "m5_ema_stack", "atr_m5", "atr_rank_1d", "execution_gate",
            "risk_check", "risk_budget", "max_affordable_stop_at_min_volume", "typical_stop_estimate", "eligible_for_next_signal",
            "why_no_trade")
    return {"count": int(len(a)), "latest": {k: last.get(k) for k in keep},
            "hourly": a[[c for c in ("ts", "bid", "spread", "m15_bias", "m5_ema_stack", "atr_m5", "signals_since_last_assessment",
                                     "eligible_for_next_signal", "why_no_trade") if c in a]].fillna("").to_dict("records")}


def paper(opens: pd.DataFrame, closes_today: pd.DataFrame, closes_all: pd.DataFrame) -> dict:
    """SIMULATED trades from real strategy signals that were not executed. Never real orders."""
    def s(df):
        if df.empty or "r_net_est" not in df:
            return {"closed": 0}
        r = df["r_net_est"].astype(float)
        return {"closed": int(len(r)), "wins": int((r > 0).sum()), "mean_r_net_est": round(float(r.mean()), 3),
                "by_skip_reason": {}}
    out = {"label": "SIMULATED - not broker orders", "opened_today": int(len(opens)), "today": s(closes_today),
           "since_start": s(closes_all)}
    if not opens.empty and "signal_reason" in opens:
        out["opened_today_by_skip_reason"] = dict(Counter(opens["signal_reason"].fillna("")))
    return out


def markdown(rep: dict) -> str:
    s, t, c = rep["status"], rep["today"], rep["cumulative"]
    L = [f"# Forward experiment {rep['experiment']}: {rep['date_utc']} (UTC)", "",
         "Demo account, XAUUSD, tds-1.0 baseline. This strategy has **no validated edge**; the experiment measures broker execution vs simulation.", ""]
    if not s["ever_started"]:
        L += ["**The cBot has not been started yet**, so no journal records exist for this experiment. Nothing to report.", ""]
    else:
        ls = s["last_start"] or {}
        L += [f"- Last start: {ls.get('ts')} | mode **{ls.get('execution_mode')}** ({ls.get('execution_gate')}) | demo verified {ls.get('demo_verified')} | account {ls.get('account')}",
              f"- Heartbeats today: {s['heartbeats_today']} (last {s['last_heartbeat']}) | halted: {s['halted_now']} {s['halt_reason'] or ''}",
              f"- LIVE account ever seen: {s['live_ever_seen']}", ""]
    sig = rep["signals"]
    L += ["## Signals", f"- Seen: {sig['total']} | decisions: {sig['decisions'] or 'none'}"]
    for k, v in (sig["skip_reasons"] or {}).items():
        L.append(f"  - skipped ({k}): {v}")
    L += ["", "## Results", "| | Trades | Net | Win % | PF | Exp. R | Commission |", "|---|---|---|---|---|---|---|",
          f"| Today | {t.get('trades', 0)} | {t.get('net', 0)} | {t.get('win_rate', '–')} | {t.get('profit_factor', '–')} | {t.get('expectancy_r', '–')} | {t.get('commission', 0)} |",
          f"| Since start | {c.get('trades', 0)} | {c.get('net', 0)} | {c.get('win_rate', '–')} | {c.get('profit_factor', '–')} | {c.get('expectancy_r', '–')} | {c.get('commission', 0)} |", ""]
    if c.get("trades", 0) < 30:
        L += [f"Evidence note: {c.get('trades', 0)} closed trades. At least 100 are needed before the result says anything about expectancy; the simulator predicted about -0.07R per trade.", ""]
    cm = rep["costs_cumulative"]
    L += ["## Execution vs simulator assumptions (since start)", "| Item | Simulator assumed | Broker actual |", "|---|---|---|",
          f"| Spread (USD/oz) | ≥ {cm['assumed']['spread_floor']} | signal median {cm.get('actual_spread_at_signal_median', '–')}, fill median {cm.get('actual_spread_at_fill_median', '–')} |",
          f"| Entry slippage (USD/oz, + = worse) | {cm['assumed']['slippage_per_fill']} | mean {cm.get('actual_entry_slippage_mean', '–')}, worst {cm.get('actual_entry_slippage_max_adverse', '–')} |",
          f"| Stop slippage (USD/oz) | {cm['assumed']['slippage_per_fill']} | mean {cm.get('actual_stop_slippage_mean', '–')} |",
          f"| Commission per side (fraction of notional) | {cm['assumed']['commission_per_side_rate']} | {cm.get('actual_commission_rate_per_side', '–')} |",
          f"| Order latency (ms) | – | median {cm.get('order_latency_ms_median', '–')} |", ""]
    rc = rep["reconciliation"]
    L += ["## Reconciliation with the simulator"]
    if not rc.get("available"):
        L += [f"- {rc.get('reason')}", ""]
    else:
        sp, fm = rc["signal_parity"], rc["fill_model"]
        L += [f"- Signal parity today: reference engine {sp['reference_candidates']} candidates on MT5 data, cBot {sp['cbot_signals']} on cTrader data, matched {sp['matched']}.",
              f"- Fill model: {fm['trades_compared']} trades replayed; same exit type {fm['same_exit_reason']}; mean R actual {fm['mean_actual_r']} vs simulated {fm['mean_sim_r']}.", ""]
    tc = rep.get("tradeden_copy") or {}
    L += ["## TradeDen copy signals (fwd-tdn-001)", f"- Received: {tc.get('received', 0)} {tc.get('by_source', '')} | decisions: {tc.get('decisions', '')}"]
    for k, v in (tc.get("skip_reasons") or {}).items():
        L.append(f"  - skipped ({k}): {v}")
    for o in tc.get("opened") or []:
        L.append(f"  - OPENED {o}")
    L.append("")
    xt = rep.get("execution_test") or []
    L += ["## EXECUTION_TEST (one-time broker check, excluded from strategy results)"]
    if not xt:
        L += ["- Not run.", ""]
    for x in xt:
        bits = [f"{k}={x.get(k)}" for k in ("status", "reason", "error", "position_id", "entry", "volume_units", "stop", "target",
                                             "spread_at_fill", "entry_commission", "exit", "commission", "net", "closing_deal_id",
                                             "max_loss_at_stop_incl_commission", "risk_budget") if x.get(k) not in (None, "")]
        L.append(f"- {x.get('ts')}: " + ", ".join(bits))
    L.append("")
    a = rep.get("assessments", {})
    L += ["## Hourly market assessments", f"- Recorded today: {a.get('count', 0)}"]
    if a.get("latest"):
        la = a["latest"]
        L += [f"- Latest ({la.get('ts')}): bid {la.get('bid')}, spread {la.get('spread')}, M15 bias {la.get('m15_bias')}, M5 EMA stack {la.get('m5_ema_stack')}, ATR(M5) {la.get('atr_m5')}",
              f"- Eligible for the next signal: {la.get('eligible_for_next_signal')} | budget {la.get('risk_budget')} | largest affordable stop at minimum volume {la.get('max_affordable_stop_at_min_volume')} vs typical stop ~{la.get('typical_stop_estimate')}",
              f"- Why no trade: {la.get('why_no_trade')}"]
    L.append("")
    pp = rep.get("paper_trades_simulated", {})
    L += ["## Paper trades (SIMULATED, not broker orders)",
          f"- Opened today: {pp.get('opened_today', 0)} {pp.get('opened_today_by_skip_reason', '')}",
          f"- Closed today: {pp.get('today', {}).get('closed', 0)}, mean R (est.) {pp.get('today', {}).get('mean_r_net_est', '–')} | since start: {pp.get('since_start', {}).get('closed', 0)}, mean R {pp.get('since_start', {}).get('mean_r_net_est', '–')}",
          "- Paper trades track real strategy signals that were not executed (for example skipped for minimum volume). They are excluded from every real result above.", ""]
    if rep["risk_events"]:
        L += ["## Risk events"] + [f"- {e['ts']} {e['event']}: {e.get('reason') or e.get('message')}" for e in rep["risk_events"]] + [""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="UTC date YYYY-MM-DD (default: yesterday and today)")
    ap.add_argument("--no-mt5", action="store_true")
    a = ap.parse_args(argv)
    events = load_events(journal_dir())
    m1 = None if a.no_mt5 else refresh_mt5_m1()
    today = datetime.now(timezone.utc).date()
    days = [datetime.strptime(a.date, "%Y-%m-%d").date()] if a.date else [today - timedelta(days=1), today]
    OUT.mkdir(exist_ok=True)
    for d in days:
        rep = build(d, events, m1)
        (OUT / f"{d}.json").write_text(json.dumps(rep, indent=1, default=str))
        (OUT / f"{d}.md").write_text(markdown(rep), encoding="utf-8")
        print(f"wrote {OUT / (str(d) + '.md')}")


if __name__ == "__main__":
    main()
