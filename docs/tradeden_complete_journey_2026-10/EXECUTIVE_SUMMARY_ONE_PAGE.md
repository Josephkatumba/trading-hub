# TradeDen — Executive Summary (one page)

**The Complete Journey: Historical Review and Strategic Roadmap · October 2026** · Founder: Joseph Katumba · Evidence cut-off 2026-10-24 (HEAD `920676d`)

**What it is.** TradeDen is a single-founder, AI-assisted trading-intelligence platform, built in five weeks (216 commits since 2026-09-21) and running on one Windows laptop. Its parts:
- a local FastAPI engine that reads live MT5 data for 16 instruments every 30 s;
- 4 production strategies, a 19-strategy bank and 17 governed research models, all in paper mode;
- Telegram delivery;
- the "Garden" web app;
- `quant_labs/`, a hash-verified research laboratory shared by Claude, Codex and Kimi agents.

No broker execution exists.

**Verdict.** The project has an excellent research and evidence discipline and **no demonstrated trading edge** [VERIFIED]:
- All production strategies lose after costs. `trendline_v5` does worse than all 20 random-entry controls.
- None of the 19 bank strategies, roughly 157 V6/T-033 configurations or about 45 lab versions is significant after correction.
- Live paper outcomes since 25 Sep: **−53.8R over 170 resolved signals (−0.32R per signal)**.
- The two paper candidates are each positive in every historical split but insignificant and seen before, with **zero forward signals**:
  - `index_trend_day` 0.2.0: +0.147R, 225 trades;
  - `crypto_trend_breakout` 0.3.0: +0.295R, 69 trades.

**Five key discoveries**
1. TradeDen is an honest machine for *rejecting* strategies. Its negative findings are robust [ASSESSMENT].
2. **Losing strategies still alert to Telegram** [VERIFIED]. Production alerts sent 37 signals and 34 follow-ups between 19 and 23 Oct, and the bank sent 65 messages. Five internal reports recommend pausing them.
3. Costs decide outcomes [VERIFIED]: tight M15 stops cost about 0.15R per trade. Only multi-hour to multi-day momentum with time exits stayed positive.
4. Data and time are the binding constraints [VERIFIED]: two years of M15/H1 and about three months of M1, all splits exposed, while small edges need 12–50 months to confirm.
5. Infrastructure is fragile [VERIFIED]:
   - about 25% engine uptime from 19 to 23 Oct;
   - the 2.6 GB store sits in OneDrive and was corrupted once (5 Oct);
   - OneDrive file locks fail jobs;
   - the outcome resolver has 5 P1 defects (independent audit).

**Five urgent recommendations** [PROPOSAL]
1. Today: shadow or pause `trendline_v5` and Trend/Momentum alerts; relabel or pause S/R, SMC and bank alerts; rotate the Telegram bot token (reported as pasted into a chat).
2. This week: move runtime state off OneDrive (the relocation tool is ready), pin the MT5 terminal path, fix the watchdog relaunch loop.
3. This month: fix the resolver P1 defects and re-resolve history as revisions; recheck alert authorisation at send time.
4. Freeze the strategy catalogue. Unlock the untouched 2022–2024 holdout through the MT5 maintenance window and score the two candidates on it once. Review forward paper results after about 3 months.
5. Commercialise what does not depend on edge (gold/BTC intelligence, journal, verification). Get legal advice before any paid signals, and run willingness-to-pay tests before billing.

**Scores (/10)** [ASSESSMENT]:

| Overall | Engineering | Research methodology | Strategy performance | Data infrastructure | Reliability | Commercial readiness | Scalability | Long-term potential |
|---|---|---|---|---|---|---|---|---|
| **5.0** | 7.0 | 7.5 | 1.5 | 4.5 | 3.5 | 2.5 | 3.5 | 5.5 |

**Main gaps:** history before 2026-09-21; the Telegram audience size; whether the token was rotated; spend on AI, data and tools; any market or competitor evidence; executed-trade results (none exist).

Labels: [VERIFIED] read from repository or live store · [RECONSTRUCTED] assembled history · [ASSESSMENT] reviewer judgement · [PROPOSAL] not yet existing. Full report: `TRADEDEN_COMPLETE_JOURNEY_2026-10.md` / `.pdf`.
