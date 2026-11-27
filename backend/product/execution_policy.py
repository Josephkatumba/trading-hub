"""Fail-closed execution policy: the single gate any future broker adapter must pass.

This module decides; it never talks to a broker. In this release no adapter calls it to send
orders: MT5 is market-data only, and the cTrader cBot enforces its own demo-only gate
(``ctrader_scalper/cbot/TradeDenScalper.cs``). The policy exists now so that Phase 9 adapters
inherit one tested contract instead of each re-implementing safety.

Defaults (nothing to configure = nothing can execute):
- ``TRADEDEN_EXECUTION_ENABLED`` must be exactly ``"1"``; otherwise every request is denied.
- Live accounts are always denied (``LIVE_TRADING_SUPPORTED = False``); the account must
  positively report ``is_demo=True`` and ``is_live=False``.
- Every order needs a stop loss on the protective side; take profit, if given, on the other side.
- Risk per trade, daily loss, open positions and consecutive losses are capped; environment
  values above the hard ceilings are clamped down, never up.
- Only VALIDATED/PRODUCTION strategies may execute, except a declared demo forward experiment.
- An emergency stop file blocks everything until released with a reason; engage and release
  are appended to an audit log.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

LIVE_TRADING_SUPPORTED = False
HARD_CEILINGS = {"risk_per_trade_pct": 1.0, "daily_loss_pct": 3.0, "max_open_positions": 3, "max_consecutive_losses": 3}
DEFAULTS = {"risk_per_trade_pct": 0.25, "daily_loss_pct": 1.0, "max_open_positions": 1, "max_consecutive_losses": 2}
EXECUTABLE_TIERS = {"VALIDATED", "PRODUCTION"}


@dataclass(frozen=True)
class Limits:
    risk_per_trade_pct: float
    daily_loss_pct: float
    max_open_positions: int
    max_consecutive_losses: int


@dataclass(frozen=True)
class Config:
    enabled: bool
    mode: str            # "disabled" | "demo"
    limits: Limits
    problems: tuple[str, ...] = ()


def _number(env: Mapping[str, str], name: str, key: str, problems: list[str]) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return DEFAULTS[key]
    try:
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError
    except ValueError:
        problems.append(f"{name} is invalid; default used")
        return DEFAULTS[key]
    if value > HARD_CEILINGS[key]:
        problems.append(f"{name}={raw} exceeds the hard ceiling {HARD_CEILINGS[key]}; clamped")
        return HARD_CEILINGS[key]
    return value


def config_from_env(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    problems: list[str] = []
    enabled = env.get("TRADEDEN_EXECUTION_ENABLED") == "1"
    mode = (env.get("TRADEDEN_EXECUTION_MODE") or "demo").strip().lower()
    if mode != "demo":
        problems.append(f"TRADEDEN_EXECUTION_MODE={mode!r} is not supported; only 'demo' exists. Execution disabled")
        enabled = False
    limits = Limits(
        _number(env, "TRADEDEN_MAX_RISK_PER_TRADE_PCT", "risk_per_trade_pct", problems),
        _number(env, "TRADEDEN_MAX_DAILY_LOSS_PCT", "daily_loss_pct", problems),
        int(_number(env, "TRADEDEN_MAX_OPEN_POSITIONS", "max_open_positions", problems)),
        int(_number(env, "TRADEDEN_MAX_CONSECUTIVE_LOSSES", "max_consecutive_losses", problems)))
    return Config(enabled, "demo" if enabled else "disabled", limits, tuple(problems))


# ----- emergency stop ------------------------------------------------------------------------------

def execution_dir() -> Path:
    from storage_config import data_directory
    return data_directory() / "execution"


def _stop_file(folder: Path | None) -> Path:
    return (folder or execution_dir()) / "EMERGENCY_STOP"


def _audit(folder: Path | None, row: dict[str, Any]) -> None:
    path = (folder or execution_dir()) / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def emergency_stop_state(folder: Path | None = None) -> dict[str, Any] | None:
    path = _stop_file(folder)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"reason": "unreadable stop file (treated as engaged)"}


def engage_emergency_stop(reason: str, actor: str = "operator", folder: Path | None = None) -> dict[str, Any]:
    """Always allowed (it only makes the system safer)."""
    row = {"event": "EMERGENCY_STOP_ENGAGED", "at": datetime.now(timezone.utc).isoformat(),
           "actor": actor, "reason": reason.strip() or "unspecified"}
    path = _stop_file(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row), encoding="utf-8")
    _audit(folder, row)
    return row


def release_emergency_stop(reason: str, actor: str = "operator", folder: Path | None = None) -> dict[str, Any] | None:
    if not reason or not reason.strip():
        raise ValueError("releasing the emergency stop requires a reason")
    path = _stop_file(folder)
    if not path.exists():
        return None
    path.unlink()
    row = {"event": "EMERGENCY_STOP_RELEASED", "at": datetime.now(timezone.utc).isoformat(), "actor": actor,
           "reason": reason.strip()}
    _audit(folder, row)
    return row


# ----- decision ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reasons": list(self.reasons)}


def _f(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def evaluate(order: Mapping[str, Any], account: Mapping[str, Any], config: Config,
             stop_state: dict[str, Any] | None) -> Decision:
    """Every failed check is reported; any failure denies."""
    reasons: list[str] = []
    if not config.enabled:
        reasons.append("execution is disabled (TRADEDEN_EXECUTION_ENABLED is not '1')")
    if stop_state is not None:
        reasons.append(f"emergency stop engaged: {stop_state.get('reason', 'no reason recorded')}")
    if account.get("is_live") is not False or account.get("is_demo") is not True:
        reasons.append("account must positively report is_demo=True and is_live=False; live trading is not supported")

    side = str(order.get("side") or "").upper()
    entry, sl, tp = _f(order.get("entry")), _f(order.get("stop_loss")), _f(order.get("take_profit"))
    if side not in {"BUY", "SELL"}:
        reasons.append("side must be BUY or SELL")
    if entry is None or entry <= 0:
        reasons.append("a positive entry price is required")
    if sl is None:
        reasons.append("a stop loss is required")
    elif entry is not None and side in {"BUY", "SELL"} and ((side == "BUY" and sl >= entry) or (side == "SELL" and sl <= entry)):
        reasons.append("stop loss is not on the protective side of entry")
    if tp is not None and entry is not None and side in {"BUY", "SELL"} and (
            (side == "BUY" and tp <= entry) or (side == "SELL" and tp >= entry)):
        reasons.append("take profit is not on the profit side of entry")

    limits = config.limits
    risk = _f(order.get("risk_pct"))
    if risk is None or risk <= 0:
        reasons.append("risk_pct is required")
    elif risk > limits.risk_per_trade_pct:
        reasons.append(f"risk {risk}% exceeds the per-trade limit {limits.risk_per_trade_pct}%")
    day_loss = _f(account.get("daily_loss_pct"))
    if day_loss is None:
        reasons.append("daily loss is unknown")
    elif day_loss + (risk or 0) > limits.daily_loss_pct:
        reasons.append(f"daily loss {day_loss}% plus this risk would exceed {limits.daily_loss_pct}%")
    open_positions = account.get("open_positions")
    if not isinstance(open_positions, int) or open_positions < 0:
        reasons.append("open position count is unknown")
    elif open_positions >= limits.max_open_positions:
        reasons.append(f"{open_positions} open positions (limit {limits.max_open_positions})")
    losses = account.get("consecutive_losses")
    if not isinstance(losses, int) or losses < 0:
        reasons.append("consecutive loss count is unknown")
    elif losses >= limits.max_consecutive_losses:
        reasons.append(f"{losses} consecutive losses (halt at {limits.max_consecutive_losses})")

    tier = order.get("strategy_tier")
    if tier not in EXECUTABLE_TIERS and order.get("forward_experiment") is not True:
        reasons.append(f"strategy tier {tier or 'unknown'} is not executable (needs VALIDATED/PRODUCTION "
                       "or a declared demo forward experiment)")
    return Decision(not reasons, tuple(reasons))


def status(config: Config | None = None, folder: Path | None = None) -> dict[str, Any]:
    config = config or config_from_env()
    stop = emergency_stop_state(folder)
    return {"execution_enabled": config.enabled and stop is None, "mode": config.mode,
            "live_trading_supported": LIVE_TRADING_SUPPORTED, "emergency_stop": stop,
            "limits": asdict(config.limits), "hard_ceilings": HARD_CEILINGS, "config_problems": list(config.problems),
            "adapters": {
                "mt5": {"state": "MARKET_DATA_ONLY", "orders": False,
                        "note": "The engine reads quotes and bars; it contains no order path."},
                "ctrader": {"state": "DEMO_FORWARD_GATED_IN_CBOT", "orders": "demo only, after manual activation",
                            "note": "TradeDenScalper refuses live accounts and needs an activation code and exact demo "
                                    "account number; see ctrader_scalper/forward/ACTIVATION_CHECKLIST.md."}}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m product.execution_policy")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for name in ("stop", "release"):
        p = sub.add_parser(name)
        p.add_argument("reason")
    args = parser.parse_args(argv)
    if args.cmd == "stop":
        print(json.dumps(engage_emergency_stop(args.reason, actor="cli"), indent=2))
    elif args.cmd == "release":
        print(json.dumps(release_emergency_stop(args.reason, actor="cli"), indent=2))
    else:
        print(json.dumps(status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
