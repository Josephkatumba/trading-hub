# Phase 2 — Gold & Bitcoin intelligence (CEO report, 2026-10-23)

## Completed work

A new **explainable market-intelligence engine**, `backend/market_intel/`, covers XAUUSD and BTCUSD. It is built from pure functions over **closed MT5 candles only**, and each conclusion comes from a numbered rule (`rules.RULES`):

| Area | Rules | What it produces |
|---|---|---|
| Higher-timeframe structure | T1 | D1 / H4 / H1 trend (EMA20/EMA50 with slope) and the values behind it |
| Key levels | L1–L4 | previous broker-day and previous-week high/low; H4 swing highs/lows (confirmed pivots); 20-day high/low |
| Level behaviour | E1 | ACCEPTED, FAILED breakout, liquidity SWEEP, UNTESTED or FORMING, using only candles **after** the level existed |
| Sessions | S1–S2 | Asia, London and New York (DST-aware), the overlap, the pre-New-York London range, and whether New York took London's high or low |
| Regime | R1–R4 | trending / ranging / mixed; volatility percentile (low / normal / high); daily range expansion; volatility shock (cause stated as **unverified**) |
| Scenarios | C1–C3 | bullish and bearish confirmation **conditions** with met / not met; reasons to avoid directional trades |
| Gold macro | — | US dollar proxy from the seven broker USD pairs, **labelled as a proxy, not the DXY** |
| Bitcoin specifics | — | weekend flag, US cash-session flag, BTC–NAS100 correlation from synchronised hourly returns |

* **Marked UNAVAILABLE, never estimated:**
  * Treasury yields, real yields, the economic calendar (Fed, CPI, NFP) and geopolitical risk. The engine terminal's broker has no DXY, Treasury or VIX instrument.
  * BTC funding rates, open interest, liquidations and spot/perpetual divergence. No trusted source is connected, and liquidations are not inferred from candles.
* Each conclusion carries its supporting observations, rules, data timestamp, and any missing or conflicting evidence. There are no confidence percentages, and **no entry, stop or target is ever produced**.
* **Delivery:**
  * a loopback-only API, `/api/quant-labs/intelligence/{XAUUSD|BTCUSD}`;
  * gold and bitcoin cards in the existing Quant Labs dashboard view;
  * an **internal Telegram preview** from `python -m market_intel XAUUSD`. Nothing is scheduled or sent.

## Verified tests

* `tests/test_market_intel.py`: 8 tests, all passing. They cover:
  * rule unit cases;
  * the DST-aware session clock (summer and winter, overlap, weekend);
  * no trade levels anywhere in the output;
  * unavailable data labelled as unavailable;
  * every conclusion explained;
  * the stale-data flag;
  * the loopback/symbol API guard;
  * **no look-ahead on genuine historical gold and bitcoin data**: identical output whether or not future candles are supplied.
* **Two real defects were found by running on live data and the tests, and fixed:**
  1. Level events looked at candles from before the level existed.
  2. The London session ended before New York opened, so an "overlap" could never occur.
* Regression: 96 backend tests and 186 frontend tests pass.

## Operational status

* The internal previews work now on live data. Example from 01:3x UTC:
  * Gold: structure DOWN on D1/H4/H1, trending, high volatility, trading at its 20-day low.
  * Bitcoin: D1 UP versus H4 DOWN. That conflict produces a "caution" condition. BTC–NAS100 hourly correlation is +0.56 over 120h.
* The API and dashboard cards are **inactive until the next engine restart**, because they're engine code.
* The existing alerts, reports and approved signal delivery are unchanged.

## Research findings and limitations

* This phase builds **analysis**, not edge. Whether these regime and structure conditions improve strategy expectancy is Phase 3's job, tested on the frozen evaluator without touching the exposed test split again.
* The live candle cache holds about 199 H4 and D1 candles and 600 H1. That's enough for the rules, but regime history in the live view is limited to about 25 days.
* Macro and crypto-derivatives evidence stays unavailable until you approve a free, authoritative source. Candidates: official Fed and BLS release calendars; exchange public APIs for funding and open interest. Both need review of terms and reliability.

## Required CEO decisions

1. **Engine restart** to activate the intelligence API and dashboard cards (engine only).
2. Whether to connect free official sources for the economic calendar, and free exchange APIs for BTC funding and open interest.
3. Scheduled gold and bitcoin intelligence messages stay **off** until you approve them.
4. The push decision remains open (public repository).

## Next (Phase 3)

* Test whether the regime and structure rules separate good from bad trades for the existing gold and bitcoin strategies, pre-registered, using train and validation only.
* A small number of new gold and bitcoin hypotheses, pre-registered, with simple baselines.
