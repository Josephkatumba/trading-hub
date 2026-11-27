# TRADEDEN Strategy Intelligence — ICT family, upgrades, evidence tiers, confluence

All of this is **research / shadow**. Nothing here places orders, unlocks execution, changes risk
limits or touches broker credentials. New strategies are registered in the Strategy Bank as
`RESEARCH`: they are scanned live, recorded and outcome-tracked, and **never alerted** until an
evidence-gated promotion (`strategy_bank/qualification.py`) plus your approval.

| Piece | Code |
|---|---|
| ICT primitives + 8 setups | `backend/strategy_bank/ict.py` |
| Upgraded versions of weak strategies | `backend/strategy_bank/upgrades.py` |
| Evidence tiers | `backend/strategy_bank/evidence_tiers.py` |
| Historical evaluation runner | `backend/research/strategy_intel.py` → `data/strategy_bank/intel.json` |
| Confluence engine | `backend/confluence.py` |
| API | `backend/intelligence_api.py` (`/api/intelligence/strategies`, `/market`, `/overview`) |
| Tests | `backend/tests/test_ict_strategies.py`, `tests/terminalModel.test.mjs` |

## 1. ICT family (`ict-family-v1.1`)

Execution timeframe M15; context from H1 and H4 (D1 is deliberately not used: live D1 context is
stale every Monday). Times are New York (DST-aware); the trading day rolls at 17:00 New York.

### Primitives

| Concept | Objective definition |
|---|---|
| Liquidity pools | BSL above / SSL below: previous day high/low (PDH/PDL), previous week high/low (PWH/PWL, from H1), Asian range 20:00–00:00 NY, London kill-zone range 02:00–05:00 NY, equal highs/lows (two confirmed 3-bar swings within 0.1 ATR, unswept), last confirmed swing high/low |
| Sweep / stop hunt | a candle trades beyond an unswept pool and closes back inside, on the same candle or the next (two-candle reclaim) |
| Swing / structure | 3-bar pivots (confirmed 3 bars later). BULLISH = HH + HL, BEARISH = LH + LL |
| MSS / CHoCH | after a sweep, the first close beyond the swing point that preceded the sweep |
| BOS | a close beyond the last swing in the direction of the structure |
| Displacement | body ≥ 0.8 ATR and ≥ 55% of the candle range |
| FVG | 3-candle imbalance ≥ 0.2 ATR whose middle candle is a displacement; mitigated on first touch; invalidated by a close beyond the far edge; CE = midpoint |
| Order block (H1) | last opposite candle before a displacement that closes beyond the last swing (BOS); broken → breaker |
| Dealing range (H1) | last confirmed swing high/low; equilibrium 50%; premium/discount; OTE = 62–79% retracement |
| HTF bias | H4 swing structure |
| Kill zones | London 02–05, NY AM 07–10, Silver Bullet 03–04 / 10–11 / 14–15 (NY) |

### Setups (stages WATCHING → DEVELOPING → CONFIRMING → CONFIRMED)

A pool, gap or block on its own is never a signal. Every setup requires a sweep and/or structure
shift **plus** a closed-candle confirmation. Common risk rules: stop 0.1 ATR beyond the structural
extreme, at least 0.5 ATR, skipped beyond 3 ATR; target = nearest unswept opposing pool at 2–5R,
else a fixed 2.5R; minimum R:R 2.0; the bank's gates (fresh data, entry drift ≤ 0.5 ATR, spread ≤
25% of risk) apply on top.

1. **Liquidity Sweep Reversal** — external pool swept, then within 3 bars a displacement close beyond the sweep candle; H4 bias not opposing. 8-hour time exit.
2. **Market Structure Shift** — opposing M15 structure, a sweep within 12 bars, first displacement close through the pre-sweep swing.
3. **FVG Continuation** — H4 bias and H1 structure aligned; displacement FVG that broke M15 structure; first retest closes beyond CE.
4. **Order Block Reversal** — fresh H1 OB in discount (longs) / premium (shorts); first M15 visit; M15 close beyond the prior two candles.
5. **Premium/Discount OTE** — H4 bias aligned; H1 impulse ≥ 2 H1 ATR that broke structure; retrace into 62–79%; M15 confirmation; target the leg extreme.
6. **Silver Bullet** — M15 approximation (canonical is M1–M5): FVG in the window after an opposite sweep; first retest beyond CE; 2-hour exit.
7. **Judas Swing** — H4 bias not opposing; 02:00–10:00 NY sweep of the Asian range against the bias, then a displacement shift back through the Asian level.
8. **Sweep + Displacement + FVG** — London / NY AM: external sweep, MSS with displacement leaving an FVG, first retest beyond CE.

Parameters were fixed before any backtest (`ict.PARAMS`). One change was made before the full run,
on trade-frequency diagnostics only (not P&L): v1.1 allows a two-candle sweep reclaim and relaxes
the Judas bias to "not opposing". This is recorded in the code header.

## 2. Strategy audit and upgrades (`bank-upgrades-v1`)

The originals keep running unchanged; each upgrade is a separate RESEARCH strategy with a new
hypothesis (not a threshold tweak). See `upgrades.py` for the full rules.

| Upgrade | Replaces | Hypothesis |
|---|---|---|
| Compression Breakout v2 | breakout, donchian, atr_breakout, inside_bar | breakouts from a volatility squeeze, with displacement, aligned with H4, during liquid hours |
| Trend Pullback v2 | ema_pullback, ema_crossover, ichimoku | pullbacks pay only in a trend regime (ADX), entered on resumption with a structural stop |
| Trend Momentum v2 | macd_momentum, ema_crossover | momentum crosses matter only when trend strength is rising |
| Liquidity Divergence v2 | rsi_divergence | divergence at a fresh two-day extreme (stops taken), outside strong trends |
| Opening Range Breakout v2 | opening_range_breakout | normal-width ranges broken in the H1 trend direction, midpoint stop |
| Crypto Trend Breakout v2 | donchian, breakout | crypto time-series momentum: 2-day breakouts with the H4 trend, 3R |

The production-linked strategies (Trendline Break & Retest, Trendline Bounce, Support &
Resistance) are not modified; the Strategy Lab shows where they fail by session and regime.

## 3. Evidence tiers

Computed from evidence only (`evidence_tiers.py`), never from signal count or deployment status:

- **SUSPENDED** — all-period 95% CI of expectancy entirely below zero after costs. Suspension is *recommended*; nothing is switched off automatically.
- **EXPERIMENTAL** — < 100 trades, or expectancy ≤ 0 without being significantly negative.
- **RESEARCH** — positive after costs but fails at least one test.
- **VALIDATED** — passes all of: ≥ 100 trades (≥ 30 in test); expectancy > 0 in development and in the untouched test period; CI lower bound > 0 and Holm-adjusted p < 0.05 across every strategy evaluated; expectancy > 0 with doubled costs; positive in ≥ 2/3 of walk-forward folds.
- **PRODUCTION** — VALIDATED + a forward record meeting the promotion gate (≥ 60 resolved, ≥ 0.05R, PF ≥ 1.10) + deployment approval.

Look-ahead bias: `decide(ctx, i)` sees closed bars only; tests assert that every ICT stage report
and every upgrade decision is identical with and without future bars. Overfitting: no parameter
search, separate test period, doubled-cost stress, walk-forward folds, Holm correction. The test
window was previously viewed for related families (V6/T-033), so it is not pristine for FVG,
order-block and sweep ideas.

## 4. Confluence engine

Strategies that read the same evidence are not independent. Every strategy belongs to one evidence
family (liquidity & structure, imbalance & PD arrays, trend & momentum, trendline, levels & mean
reversion, session & time). Confluence counts **families**, never strategies or scores; WATCHING
does not vote; a family whose members disagree is CONFLICTED. Classifications: NONE, MIXED,
DIRECTIONAL AGREEMENT (≥ 2 families, nothing confirmed), CONFIRMED CONFLUENCE (≥ 2 families and at
least one confirmed entry). When no contributor is VALIDATED the result says so explicitly.

## 5. Running it

```
cd backend
python -m research.strategy_intel                    # full evaluation, writes data/strategy_bank/intel.json
python tests/run_suite.py                            # backend tests
```

The new endpoints load when the market engine restarts. Until then the frontend shows the
intelligence panels as unavailable; all existing features keep working.
