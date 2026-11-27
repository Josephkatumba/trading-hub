"""Research report tables from data/strategy_bank/intel.json (read-only; prints Markdown).

    python -m research.intel_report > ../docs/STRATEGY_EVALUATION_BASELINE_TABLES.md
"""
from __future__ import annotations

import json
import math
from typing import Any

from strategy_bank import engine

MIN_GROUP = 30          # trades needed before a conditional "best" is reported


def load() -> dict[str, Any]:
    return json.loads((engine.bank_dir() / "intel.json").read_text(encoding="utf-8"))


def f(v, d=3, sign=True):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return (f"{v:+.{d}f}" if sign else f"{v:.{d}f}")


def best(group: dict[str, Any]) -> str:
    rows = [(k, v) for k, v in (group or {}).items() if k != "UNKNOWN" and (v.get("trades") or 0) >= MIN_GROUP]
    if not rows:
        return "— (no group with 30+ trades)"
    k, v = max(rows, key=lambda kv: kv[1]["expectancy_r"])
    return f"{k} {f(v['expectancy_r'], 2)}R (n={v['trades']}, PF {f(v['profit_factor'], 2, False)})"


def worst(group: dict[str, Any]) -> str:
    rows = [(k, v) for k, v in (group or {}).items() if k != "UNKNOWN" and (v.get("trades") or 0) >= MIN_GROUP]
    if not rows:
        return "—"
    k, v = min(rows, key=lambda kv: kv[1]["expectancy_r"])
    return f"{k} {f(v['expectancy_r'], 2)}R (n={v['trades']})"


def pooled(rows: list[dict[str, Any]], period: str = "all_periods") -> dict[str, Any]:
    n = sum((r["performance"][period]["trades"] or 0) for r in rows)
    tot = sum((r["performance"][period]["total_r"] or 0) for r in rows)
    return {"strategies": len(rows), "trades": n, "expectancy_r": tot / n if n else None, "total_r": tot}


def main() -> None:
    d = load()
    S = {k: v for k, v in d["strategies"].items() if v.get("performance")}
    unsupported = [k for k, v in d["strategies"].items() if not v.get("performance")]
    order = sorted(S, key=lambda k: -(S[k]["performance"]["all_periods"]["expectancy_ci95"][0] or -9))
    print(f"# Strategy evaluation baseline — tables\n\nGenerated {d['generated_at']} · {d['label']}\n")
    print(f"Periods: train {d['periods']['train']}, validation {d['periods']['validation']}, test {d['periods']['test']}. {d['costs']}. {d['protocol']['multiple_testing']}.\n")

    print("## 1. Ranking by statistical reliability (lower bound of the 95% CI of expectancy, all periods)\n")
    print("| # | Strategy | Family | Tier | Trades | Win | Avg R | 95% CI | PF | Max DD (R) | Avg R:R | Holm p |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, k in enumerate(order, 1):
        v = S[k]; a = v["performance"]["all_periods"]; ci = a["expectancy_ci95"]
        print(f"| {n} | {v['name']} | {v['family']} | {v['evidence']['tier']} | {a['trades']} | {f(a['win_rate'], 3, False)} | {f(a['expectancy_r'])} | "
              f"[{f(ci[0], 3)}, {f(ci[1], 3)}] | {f(a['profit_factor'], 2, False)} | {f(a['max_drawdown_r'], 1, False)} | {f(v['performance'].get('avg_planned_rr'), 2, False)} | {f(v.get('holm_p'), 3, False)} |")
    print(f"\nNot evaluable: {', '.join(unsupported) or 'none'}.\n")

    print("## 2. Out-of-sample, walk-forward and 2x-cost stress\n")
    print("| Strategy | Dev E | Test E | Test n | Test CI | All E | x2-cost E | Survives x2 | WF folds + | Validation checks failed |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k in order:
        v = S[k]; p = v["performance"]
        wf = [x for x in p["walk_forward"] if x.get("trades")]
        pos = sum(1 for x in wf if (x["expectancy_r"] or 0) > 0)
        failed = [c for c, x in (v["evidence"].get("checks") or {}).items() if not x["pass"]]
        x2 = p["all_periods_x2_costs"]["expectancy_r"]
        print(f"| {v['name']} | {f(p['development']['expectancy_r'])} | {f(p['test']['expectancy_r'])} | {p['test']['trades']} | "
              f"[{f(p['test']['expectancy_ci95'][0], 2)}, {f(p['test']['expectancy_ci95'][1], 2)}] | {f(p['all_periods']['expectancy_r'])} | {f(x2)} | "
              f"{'yes' if (x2 or -1) > 0 else 'no'} | {pos}/{len(wf)} | {', '.join(failed) or 'none'} |")

    print("\n## 3. Best and worst conditions per strategy (groups with 30+ trades)\n")
    print("| Strategy | Best instrument | Worst instrument | Best session | Best trend regime | Best volatility regime |")
    print("|---|---|---|---|---|---|")
    for k in order:
        p = S[k]["performance"]
        print(f"| {S[k]['name']} | {best(p['by_instrument'])} | {worst(p['by_instrument'])} | {best(p['by_session'])} | {best(p['by_trend_regime'])} | {best(p['by_volatility_regime'])} |")

    print("\n## 4. Families pooled (all periods, after costs)\n")
    fam: dict[str, list] = {}
    for k, v in S.items():
        fam.setdefault(v["family"], []).append(v)
    print("| Family | Strategies | Trades | Pooled avg R | Pooled total R | Test-period avg R |")
    print("|---|---|---|---|---|---|")
    for name, rows in sorted(fam.items()):
        a, t = pooled(rows), pooled(rows, "test")
        print(f"| {name} | {a['strategies']} | {a['trades']} | {f(a['expectancy_r'])} | {f(a['total_r'], 1)} | {f(t['expectancy_r'])} |")

    print("\n## 5. Technical funnels of the new strategies (historical decisions -> accepted signals)\n")
    for k in order:
        v = S[k]
        if v["family"] in ("ICT", "UPGRADE"):
            t = v.get("technical") or {}
            rej = {x: y for x, y in t.items() if x.startswith("rejected")}
            print(f"- **{v['name']}**: {t.get('decisions', 0)} decisions, {t.get('accepted', 0)} accepted" + (f"; rejected: {rej}" if rej else ""))


if __name__ == "__main__":
    main()
