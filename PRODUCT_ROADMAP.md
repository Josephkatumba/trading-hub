# TRADEDEN Product Roadmap

"Discover opportunities. Validate strategies. Trade intelligently."

Updated 2026-11-24. Supersedes `ROADMAP.md` for product planning (that file stays as the
engine/research history). Status: **DONE**, **IN PROGRESS**, **NEXT**, **PLANNED**, **GATED**
(needs an external decision or evidence).

## Positioning decision (needs owner confirmation)

With no validated edge on record, TRADEDEN launches as a **trading intelligence and research
platform with radical transparency**: radar, grounded analysis, a signal centre that shows every
loss, and research tools. It does not launch as a profit-promising signal service. The AUTOMATED tier
stays demo-only until a strategy reaches VALIDATED on forward evidence.

## Phases

| # | Phase | Status | Exit criteria |
|---|---|---|---|
| 1 | Repository audit and product architecture | **DONE** (2026-11-24) | Audit, architecture, roadmap, log, issues; product layer with evidence tiers, plan catalogue, execution policy; tests green |
| 2 | Commercial frontend and dashboard | **NEXT** | 8-section terminal navigation; Overview with Garden as hero; dark terminal design tokens; existing views re-homed, not rewritten; Playwright smoke per section |
| 3 | Market Radar integration | PLANNED | Per-instrument market state (direction, volatility regime, trend, nearest S/R) from engine data; watchlists per user; scanner split into its own process |
| 4 | Signal Centre | PLANNED | Unified Signal read model over engine/bank/cBot; table with filters; every outcome incl. EXPIRED/INVALIDATED; confidence labelled uncalibrated |
| 5 | AI Market Analyst | PLANNED | Facts builder from engine data; optional LLM narrator receiving facts only; output validator rejects numbers not in the facts; "what would invalidate this" from strategy rules |
| 6 | Strategy Intelligence | PLANNED | One catalogue across bank/research/cBot with tiers; walk-forward/OOS/cost reports surfaced; strategy lifecycle actions for operators only |
| 7 | Performance Analytics | PLANNED | Daily/weekly/monthly R calendar from recorded signals; strategy and instrument breakdowns; account equity from recorded fills only |
| 8 | Authentication and subscriptions | PLANNED | Migration 0002 (4 tiers, watchlists, notification prefs, profiles); capability-based route guards; billing provider integration **GATED** on security review |
| 9 | Execution integration | **GATED** | Adapter interface behind `execution_policy`; demo accounts only; position monitor and execution log; live trading remains out of scope until an owner decision with legal review |
| 10 | Security audit and private beta | PLANNED | External review, data dir off OneDrive, backups and restore drill, rate limits, dependency pinning, privacy policy and risk disclosures |

## Next milestone (Phase 2), concretely

1. Add the 8-item navigation shell (`src/shell.css`, `src/main.js` NAV) and route existing views:
   Overview (Garden + status), Market Radar (Markets), AI Analyst (Analyst), Signal Centre
   (Setup performance + Alerts), Strategy Lab (Strategy Lab + Bank + Signal Quality +
   Research), Portfolio (journal), Analytics (behaviour analytics), Settings (account, plan
   from `/api/platform/plans`).
2. Introduce design tokens (dark terminal palette, tabular numerals, density scale) without
   removing the Garden styles.
3. Strategy evidence badges in Strategy Lab from `/api/platform/strategies/evidence`.
4. Execution status card (disabled / emergency stop) from `/api/platform/execution/status`.
5. Pin `vite` to an exact version.

## Commercial prerequisites (non-engineering)

- Regulatory review of signal and automation offerings in target markets (not investment advice
  disclosures, jurisdiction limits).
- Risk disclosure and terms of service before any paid plan.
- Pricing validation with beta users (prices are provisional).
