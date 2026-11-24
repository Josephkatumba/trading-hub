# TRADEDEN Known Issues

Updated 2026-11-24. Severity: **High** (data/safety/commercial risk), **Medium**, **Low**.
Each item: what, impact, plan.

## High

1. **Canonical data store inside OneDrive (9.3 GB).** `backend/data/` was corrupted once
   (2026-10-05, 127 quarantined lines). Impact: research integrity. Plan: set
   `TRADING_HUB_DATA_DIR` to a non-synced absolute path; verify with `store_audit.py`. This is an
   operator action, so the configuration was not changed automatically.
2. **No validated strategy edge.** All research programs concluded NO_EDGE. Strategy Bank
   forward results include strategies that clear the alert gate (60 / 0.05R / 1.10) by noise.
   Impact: anything marketed as "profitable signals" would be misleading. Plan: product evidence
   tiers (done); positioning decision in `PRODUCT_ROADMAP.md`.
3. **Strategy Bank QUALIFIED gate has no significance test.** `qualification.promote()` can
   promote on thresholds alone (plus CEO approval). The product tier now adds a
   Bonferroni-corrected bound, but the registry gate itself is unchanged (no silent change to
   alerting behaviour). Plan: owner decision on whether to add the same test to `promote()`.
4. **Private mode has no authentication.** It is safe only bound to loopback. Plan: refuse to
   start in private mode on a non-loopback bind (Phase 10).

## Medium

5. **Registry status naming.** `PRODUCTION` / `APPROVED_EXPERIMENTAL` in
   `strategy_bank/qualification.py` read as endorsements. UI already shows "Live · not proven
   profitable"; API consumers should use `/api/platform/strategies/evidence`.
6. **Cost basis of Strategy Bank R multiples is not uniform.** Some exits account for spread;
   commission and slippage are not modelled in bank forward R. Impact: forward expectancy is likely
   optimistic. Plan: Phase 6 cost model per instrument.
7. **"Confidence" is not a probability.** Rule points and quality scores are uncalibrated. Plan:
   Signal Centre labels (Phase 4).
8. **Three signal schemas** (engine, bank, cBot). Plan: unified Signal read model (Phase 4).
9. **Two-tier entitlement schema** (`free`/`pro` CHECK constraint). PROFESSIONAL/AUTOMATED are
   not grantable. Plan: migration 0002 (Phase 8).
10. **Single process for scanning and API.** It limits scaling and isolation. Plan: Phase 3 split.
11. **`main.py` is 1,400 lines.** Plan: extract routers per module as each phase touches them.
12. **Branch `tradeden-demo-forward` has uncommitted forward report changes**
    (`ctrader_scalper/forward/reports/2026-11-2{2,3}.*`). They were left untouched by Phase 1 so
    historical research is not overwritten.

## Low

13. `"vite": "latest"` is unpinned.
14. Committed binaries: `ctrader_scalper/buildTradeDenScalper.dll`, `quant_labs/state/runtime_relocation/*.zip`.
15. 54 untracked `*.log` files and many report markdowns at the repo root.
16. Research spread across `backend/research`, `quant_labs`, `research_autonomous`,
    `audit_independent`, `ctrader_scalper/engine`.
17. In the FastAPI version in use, included routers appear as nested entries in
    `app.routes`. Tests should hit routes with `TestClient` rather than list paths.
