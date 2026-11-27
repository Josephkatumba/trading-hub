"""Evidence-weighted signal quality scorecard.

Model: an additive model of expectancy in R (net of costs) over categorical features,
    predicted_E = base + sum_f effect_f[bucket_f]
fitted by backfitting with empirical-Bayes shrinkage: each bucket effect is the mean residual of the
bucket's trades, pulled towards zero by SHRINK pseudo-trades (effect = sum(residual) / (n + SHRINK)).
Rare buckets therefore contribute almost nothing; only effects supported by many trades survive.
Backfitting (several passes) stops correlated features (e.g. ADX and regime) from double counting.

Grades come from the predicted expectancy with thresholds FIXED BEFORE EVALUATION (not tuned):
    A+  >= +0.30R      A  >= +0.15R      B  >= +0.05R      C  >= -0.05R      REJECTED below
then capped by two rules that cannot be argued away by indicator agreement:
  - regime compatibility: trend-following in a RANGING / LOW_VOLATILITY market, or a reversion /
    reversal setup fading a TRENDING market, is capped at C
  - minimum evidence: a strategy with fewer than MIN_EVIDENCE training trades is capped at B
Only A+ and A are CONFIRMED-grade. "Several indicators agree" cannot lift a setup above what the
historical expectancy of that combination supports.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

FEATURES = ("strategy", "symbol", "family_regime", "regime_trend", "session", "htf_h4", "htf_d1", "structure",
            "adx", "di", "rsi", "macd", "atr_ratio", "bb_width", "extension", "stop_atr", "room", "planned_rr",
            "target_vs_level", "tick_activity", "strategy_form")
SHRINK = 200.0
PASSES = 4
R_CLIP = (-2.0, 6.0)
GRADES = (("A+", 0.30), ("A", 0.15), ("B", 0.05), ("C", -0.05))
GRADE_ORDER = ("A+", "A", "B", "C", "REJECTED")
CONFIRMED_GRADES = ("A+", "A")
MIN_EVIDENCE = 300
MODEL_VERSION = "quality-scorecard-v1"


def default_path() -> Path:
    return Path(__file__).resolve().parent / "model.json"


def _cap(grade: str, ceiling: str) -> str:
    return grade if GRADE_ORDER.index(grade) >= GRADE_ORDER.index(ceiling) else ceiling


def regime_cap(features: dict[str, str]) -> tuple[str | None, str | None]:
    fam, regime, trend = features.get("family"), features.get("regime"), features.get("regime_trend")
    if fam == "trend" and regime in ("RANGING", "LOW_VOLATILITY"):
        return "C", f"trend-following setup in a {regime.lower().replace('_', ' ')} market"
    if fam in ("reversion", "reversal") and regime == "TRENDING" and trend == "against":
        return "C", "fades a trending market"
    return None, None


class QualityModel:
    def __init__(self, base: float = 0.0, effects: dict[str, dict[str, float]] | None = None,
                 counts: dict[str, dict[str, int]] | None = None, strategy_trades: dict[str, int] | None = None,
                 exits: dict[str, str] | None = None, meta: dict[str, Any] | None = None) -> None:
        self.base = base
        self.effects = effects or {}
        self.counts = counts or {}
        self.strategy_trades = strategy_trades or {}
        self.exits = exits or {}
        self.meta = meta or {}

    # ----- fitting ---------------------------------------------------------------------------------
    @classmethod
    def fit(cls, rows: Iterable[tuple[dict[str, str], float]], features: tuple[str, ...] = FEATURES,
            shrink: float = SHRINK, passes: int = PASSES, exits: dict[str, str] | None = None,
            meta: dict[str, Any] | None = None) -> "QualityModel":
        data = [(f, min(max(r, R_CLIP[0]), R_CLIP[1])) for f, r in rows if r is not None and math.isfinite(r)]
        if not data:
            raise ValueError("no training rows")
        base = sum(r for _, r in data) / len(data)
        keys = [[str(f.get(name, "unknown")) for name in features] for f, _ in data]
        effects: list[dict[str, float]] = [defaultdict(float) for _ in features]
        fitted = [base] * len(data)
        counts: list[dict[str, int]] = [defaultdict(int) for _ in features]
        for row in keys:
            for k, value in enumerate(row):
                counts[k][value] += 1
        for _ in range(passes):
            for k in range(len(features)):
                sums: dict[str, float] = defaultdict(float)
                for idx, (row, (_, r)) in enumerate(zip(keys, data)):
                    sums[row[k]] += r - (fitted[idx] - effects[k][row[k]])
                new = {v: s / (counts[k][v] + shrink) for v, s in sums.items()}
                for idx, row in enumerate(keys):
                    fitted[idx] += new[row[k]] - effects[k][row[k]]
                effects[k] = defaultdict(float, new)
        strategy_trades: dict[str, int] = defaultdict(int)
        for f, _ in data:
            strategy_trades[str(f.get("strategy"))] += 1
        return cls(base, {name: dict(effects[k]) for k, name in enumerate(features)},
                   {name: dict(counts[k]) for k, name in enumerate(features)}, dict(strategy_trades), exits,
                   {"version": MODEL_VERSION, "trades": len(data), "shrink": shrink, "passes": passes, **(meta or {})})

    # ----- scoring ---------------------------------------------------------------------------------
    def contributions(self, features: dict[str, str]) -> dict[str, float]:
        return {name: table.get(str(features.get(name, "unknown")), 0.0) for name, table in self.effects.items()}

    def predict(self, features: dict[str, str]) -> float:
        return self.base + sum(self.contributions(features).values())

    def grade(self, features: dict[str, str], apply_caps: bool = True) -> dict[str, Any]:
        contrib = self.contributions(features)
        expected = self.base + sum(contrib.values())
        grade = next((g for g, threshold in GRADES if expected >= threshold), "REJECTED")
        reasons: list[str] = []
        if apply_caps:
            ceiling, why = regime_cap(features)
            if ceiling:
                capped = _cap(grade, ceiling)
                if capped != grade:
                    reasons.append(f"capped at {ceiling}: {why}")
                grade = capped
            trades = self.strategy_trades.get(str(features.get("strategy")), 0)
            if trades < MIN_EVIDENCE:
                capped = _cap(grade, "B")
                if capped != grade:
                    reasons.append(f"capped at B: only {trades} historical trades for this strategy")
                grade = capped
        ranked = sorted(contrib.items(), key=lambda kv: kv[1])
        return {
            "grade": grade, "expected_r": round(expected, 4), "confirmable": grade in CONFIRMED_GRADES,
            "score": int(round(max(0.0, min(100.0, 50 + 100 * expected)))),
            "supporting": [f"{k}={features.get(k)} ({v:+.3f}R)" for k, v in reversed(ranked[-3:]) if v > 0.005],
            "against": [f"{k}={features.get(k)} ({v:+.3f}R)" for k, v in ranked[:3] if v < -0.005],
            "caps": reasons, "model_version": self.meta.get("version", MODEL_VERSION),
        }

    # ----- persistence -----------------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        return {"base": self.base, "effects": self.effects, "counts": self.counts,
                "strategy_trades": self.strategy_trades, "exits": self.exits, "meta": self.meta}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "QualityModel":
        return cls(data["base"], data["effects"], data.get("counts"), data.get("strategy_trades"), data.get("exits"),
                   data.get("meta"))

    def save(self, path: Path | None = None) -> Path:
        path = path or default_path()
        path.write_text(json.dumps(self.to_json(), indent=1, sort_keys=True), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "QualityModel | None":
        path = path or default_path()
        if not path.exists():
            return None
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


def form_bucket(recent: list[float], minimum: int = 20) -> str:
    """Recent performance of the strategy: mean R of its last resolved signals (causal)."""
    if len(recent) < minimum:
        return "insufficient"
    mean = sum(recent) / len(recent)
    return "<-0.2" if mean < -0.2 else "-0.2-0" if mean < 0 else "0-0.2" if mean < 0.2 else ">=0.2"
