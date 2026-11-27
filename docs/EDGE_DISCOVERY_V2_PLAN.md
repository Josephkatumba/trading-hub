# TradeDen Edge Discovery V2: XAUUSD research plan (pre-registered 2026-11-23)

This plan is pre-registered: the protocol was hashed before any result was computed.

- **Program:** `edge-discovery-v2`
- **Protocol files:** `backend/research/edge_v2/{registry,hypotheses,engine,data}.py`. Their SHA-256 is written to `backend/data/research/edge_v2/ledger.jsonl`.
- **Lock:** the runner refuses to run if any protocol file changes after registration.
- **Trial log:** every configuration × window evaluated is a ledger row, including failures.

## Why V2, and what is genuinely new

- **Prior evidence:**
  - edge-discovery-v1 (2026-11-22) ran 1,962 trials on six markets at M15–H4 and found no credible edge. Gold was the least hostile market.
  - Scalper tds-1.0 (2026-11-23) ran 288 configs at M5 and found NO_EDGE: its signals had about 0R before costs.
  - Earlier programs ran about 227 configs.
  - All of these count as context for multiple testing.
- **Most of the requested families overlap v1.** These were already tested there: stop-hunt, failed Asian breakout, displacement, opening range, volatility expansion and overlap continuation. V2 adds information in four ways:
  1. **Two years of older gold history** (Sep 2022 – Aug 2024), not used by any prior program. It is a different regime: gold at $1,650–2,500, choppier. It is **sealed** as a holdout.
  2. **Gold-only rules defined by exchange clocks** (London 08:00, New York 09:30, US data release at 08:30, 10:00 and 14:00 New York), with a news-risk filter.
  3. **A direction-randomised control** for every hypothesis: same bars, stops, targets and exits, random direction. The direction call must beat 90% of 200 such controls.
  4. **A diagnosis of why tds-1.0 had zero gross expectancy** (`diagnose_v1.py`), run on development data only.

## Data and costs

| Item | Detail |
|---|---|
| Grid | XAUUSD M15 from IC Markets MT5 (2022-08-31 to 2026-11-23), broker time converted to UTC (New York + 7h), trading day rolls at 17:00 New York |
| Spread | Recorded bar spread, floored at $0.08/oz; ask = bid + spread |
| Slippage | $0.03/oz per market fill (entry, stop, time exit); targets are limit fills |
| Commission | $3 per $100k notional per side (cTrader Raw), about $0.22/oz round turn at $3,600 |
| Stress | Every holdout result is re-run at 2× all costs |
| Fill rules | Decide at bar close, enter at the next open. Stop counts first when stop and target fall in the same bar. A gap through the stop fills at the open. No entry into the rollover bars (16:45–18:15 New York), the release bars (08:30, 10:00, 14:00 New York) or after 16:00 New York on Friday. Stops tighter than 0.5 ATR(14) are rejected. |

## Chronological splits

| Split | Period | Use |
|---|---|---|
| Holdout, early (sealed) | 2022-09-01 → 2024-09-01 | One shot, gate-2 survivors only |
| Development | 2024-09-01 → 2026-07-01 | All selection: walk-forward with 26-week train and 13-week test windows |
| Holdout, recent (sealed) | 2026-07-01 → 2026-11-24 | One shot, gate-2 survivors only |

**Honesty note:** the recent holdout overlaps the test window of edge-discovery-v1 (to 12 Oct 2026) and the M1 period of tds-1.0. Those programs tested different rules, so no V2 rule has been fitted to it. The early holdout is fully untouched.

## Hypotheses (8 families × 8 configs = 64 configs; config 0 = pre-declared defaults)

| ID | Model | Free parameters |
|---|---|---|
| H1 | Market-structure break with a displacement candle (fractal swing broken by a ≥1.5–2 ATR, ≥60%-body bar) | displacement size, 2R/3R, H4 trend filter |
| H2 | Liquidity sweep of the previous-day or Asian high/low, confirmed by a close back inside and beyond the sweep bar | level, confirmation window, 2R/3R |
| H3 | Opening-range breakout, London 08:00 or New York 09:30, first close beyond the range within 3 h | session, 30/60 min, 2R or session-close exit |
| H4 | Trend-day continuation: at 10:00 or 12:00 New York, the day has moved ≥0.5–0.75 ADR and closes in its outer quarter | time, move size, exit |
| H5 | Breakout from a 4-hour compression box narrower than 0.25–0.35 ADR | width, stop placement, 2R/3R |
| H6 | Gold sessions: (a) New York reverses an extended London move; (b) Asian-session stretch fade toward the session mean | variant, stretch, exit |
| H7 | News momentum: a 08:30 / 10:00 / FOMC-Wednesday 14:00 New York shock bar ≥2–3 ATR, confirmed by 1–2 closes beyond its midpoint. No entry inside the shock bar; spread must be ≤ 2× its 20-day median. | shock size, confirmation, exit |
| H8 | Failed breakout / trapped traders: a close beyond the previous-day or previous-week high/low, then a close back inside by 0.25 ATR within 2–4 bars | level, window, target |

The rules are in `hypotheses.py`. A rule change is a new protocol version.

## Gates

**Gate 1** applies to development walk-forward out-of-sample trades. All of these must hold:

- at least 40 trades;
- expectancy greater than 0R after costs;
- profit factor at least 1.10;
- one-sided p ≤ 0.10;
- beats at least 90% of the direction-randomised controls;
- at least 50% of the family's configs positive over the whole development period. This is parameter robustness: it rejects edges that exist only at one optimised setting.

**Gate 2** is one shot. It uses the config selected on the last 26 weeks of development and tests it on both sealed holdouts. All of these must hold:

- positive in each holdout;
- bootstrap 95% CI of expectancy above 0;
- positive at 2× costs;
- positive in at least 2 of 3 volatility terciles (edges fixed on development);
- positive in both trend regimes (sign of the 50-day return);
- Holm-adjusted p ≤ 0.05 across all hypotheses that reached gate 2.

**Outcome:** pass both gates → `PROMOTED_TO_SHADOW`. The cBot runs it SignalsOnly. Automated demo execution stays locked (`ExecutionUnlocked = false`) until at least 100 forward shadow signals show expectancy > 0 and PF > 1.3. Anything else → `REJECTED`. While no strategy is promoted, the overall verdict stays `NO_EDGE`.
