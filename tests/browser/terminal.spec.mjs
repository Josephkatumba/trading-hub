import { test, expect } from "@playwright/test";

const now = Date.now(), iso = t => new Date(t).toISOString();
const market = (symbol, state, dir, price) => ({ symbol, price, change_pct: dir === "LONG" ? 0.4 : -0.6, state, direction: dir, market_bias: dir === "LONG" ? "BULLISH" : "BEARISH", score: 70, atr: price * 0.002, rsi: 48, ema20: price, ema50: price, setup: "Trendline break", stage: "BREAK", timestamp: iso(now), entry: price, stop_loss: price * 0.99, take_profit: price * 1.02, rr: 2, digits: 2 });
const candles = Array.from({ length: 120 }, (_, i) => ({ time: Math.floor(now / 1000 / 900) * 900 - (120 - i) * 900, open: 100 + Math.sin(i / 5), high: 102 + Math.sin(i / 5), low: 99 + Math.sin(i / 5), close: 101 + Math.sin(i / 5) }));
const signals = Array.from({ length: 12 }, (_, i) => ({ signal_id: "sig" + i, strategy_key: "s" + (i % 3), strategy_name: "Strategy " + (i % 3), status: "EXPERIMENTAL", symbol: i % 2 ? "XAUUSD" : "BTCUSD", direction: i % 2 ? "LONG" : "SHORT", timeframe: "M15", confirmed_at: iso(now - (12 - i) * 36e5), entry: 100, stop_loss: 99, take_profit: 102, rr: 2, outcome_status: i === 11 ? "PENDING" : i % 3 ? "TARGET_HIT" : "STOP_HIT", r_multiple: i === 11 ? 0 : i % 3 ? 2 : -1, outcome_at: iso(now - (11 - i) * 36e5), quality: { grade: "B", score: 60, stage: "CONFIRMED" } }));

const pRow = (key, name, system, family, confirmed, share, flags, tier, cls) => ({ key, name, family, concepts: [], system, deployment: system === "LIVE_SCANNER" ? "LIVE" : "EXPERIMENTAL",
  scanned: true, instruments: ["XAUUSD"], live: { confirmed, active: 1, tp: 2, sl: 3, expired: 0, invalidated: 0, resolved: 5, win_rate: 0.4, expectancy_r: -0.1, total_r: -0.5 },
  live_share: share, funnel: { setups: 100, confirmed, confirmation_rate: confirmed / 100 }, historical: { trades: 500, expectancy_r: -0.1, expectancy_ci95: [-0.2, 0], evidence: { tier } },
  regimes: { by_regime: { RANGING: { trades: 40, expectancy_r: -0.1 } }, designed_for: ["RANGING"], inside_design: { expectancy_r: -0.1 }, outside_design: { expectancy_r: -0.2 }, regime_fit: "BETTER_IN_DESIGN" },
  flags, flag_notes: [], allocation: { class: cls, weight: 0, blockers: ["historical test failed: costs"], evidence_tier: tier } });
const participation = { available: true, generated_at: iso(now), notes: [], strategies: [
  pRow("trendline_v5", "Trendline", "LIVE_SCANNER", "Trendlines", 70, 0.7, ["DOMINANT", "HIGH_VOLUME_LOW_QUALITY"], "SUSPENDED", "RESEARCH"),
  pRow("smc", "SMC confluence", "LIVE_SCANNER", "Smart Money Concepts", 30, 0.3, ["UNDERREPRESENTED"], "EXPERIMENTAL", "RESEARCH"),
  pRow("orb", "Opening range", "STRATEGY_BANK", "Session-Based", 10, 1, ["PROMISING"], "RESEARCH", "EXPERIMENTAL")],
  family_coverage: [{ family: "Trendlines", strategies: ["trendline_v5"], primary: ["trendline_v5"], live_confirmations: 70, best_tier: "SUSPENDED", designed_regimes: ["RANGING"] }],
  diversification: { strategies: ["trendline_v5", "smc"], pairs: [], clusters: [["trendline_v5"], ["smc"]], effective_independent_sources: 1.8, method: "test" },
  allocation_policy: { max_weight_per_strategy: 0.25 }, variant_tests: { smc: { adopt: false, development_expectancy: { smc_A_v1: 0.04, smc_B_v2: -0.04 }, reason: "not adopted" } } };

function mockEngine(page, { down = false } = {}) {
  return page.route("**/api/**", route => {
    if (down) return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    const path = new URL(route.request().url()).pathname;
    const body =
      path === "/api/health" ? { ok: true, status: "CONNECTED", service: "engine", engine_version: "test", mt5_connected: true, mt5_status: "CONNECTED", scanner_status: "READY", execution_enabled: false, data_freshness: { status: "FRESH", age_seconds: 5, market_count: 2 } } :
      path === "/api/market/radar" ? { markets: [market("XAUUSD", "CONFIRMING", "LONG", 3500), market("BTCUSD", "DEVELOPING", "SHORT", 90000)], scan: { sequence: 1, completed_at: iso(now), status: "FRESH" } } :
      path === "/api/market/chart" ? { candles, digits: 2 } :
      path === "/api/strategy-bank/signals" ? { signals, basis: "test fixture" } :
      path === "/api/strategy-bank" ? { strategies: [{ n: 1, key: "s0", name: "Strategy 0", qualification: "PRODUCTION", timeframe: "M15", signals: 4, resolved: 4, win_rate: 0.5, expectancy_r: 0.5, total_r: 2, max_drawdown_r: 1, by_instrument: {} }], rules: [], historical: { results: { strategies: {}, periods: {} } } } :
      path === "/api/scalper/trades" ? { trades: [] } :
      path === "/api/intelligence/participation" ? participation :
      {};
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
}

test("terminal: every page renders from engine data without runtime errors", async ({ page }) => {
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.addInitScript(() => localStorage.setItem("th_engine_url", location.origin));
  await mockEngine(page);
  await page.goto("/");
  await expect(page.locator(".wordmark")).toContainText("TRADEDEN");
  await expect(page.locator("#ovMarkets")).toContainText("XAUUSD");
  for (const [id, text] of [["radar", "Market Radar"], ["analyst", "AI Analyst"], ["signals", "Signal Centre"], ["lab", "Strategy Lab"], ["participation", "Strategy Participation"], ["portfolio", "Portfolio"], ["analytics", "Analytics"], ["history", "Trade History"], ["settings", "Settings"]]) {
    await page.locator(`[data-nav="${id}"]`).click();
    await expect(page.locator("#pgTitle")).toHaveText(text);
    await expect(page.locator(".page h1")).toBeVisible();
  }
  // Radar filter + detail drawer with live chart
  await page.locator('[data-nav="radar"]').click();
  await page.locator('#rdPulse .fstep[data-v="CONFIRMING"]').click();
  await expect(page.locator(".rcard")).toHaveCount(1);
  await page.locator(".rcard").click();
  await expect(page.locator("#mdChart canvas").first()).toBeVisible();
  await page.keyboard.press("Escape");
  // Signal Centre: open signals never show a fabricated 0R result
  await page.locator('[data-nav="signals"]').click();
  await expect(page.locator("#sgTable tbody tr")).not.toHaveCount(0);
  expect(errors).toEqual([]);
});

test("terminal: an offline engine shows unavailable states, not numbers", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("th_engine_url", location.origin));
  await mockEngine(page, { down: true });
  await page.goto("/#/radar");
  await expect(page.locator("#rdBody")).toContainText("unavailable");
  await expect(page.locator("#ticker")).toContainText("no prices shown");
});

test("terminal: light and dark themes switch instantly, persist, and theme every page", async ({ page }) => {
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.addInitScript(() => localStorage.setItem("th_engine_url", location.origin));
  await mockEngine(page);
  await page.goto("/#/participation");
  await expect(page.locator("#ptTable tbody tr")).toHaveCount(3);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const bg = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bg0").trim());
  expect(await bg()).toBe("#060a14");
  await page.locator("#themeBtn").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await bg()).toBe("#eef1f6");
  expect(await page.evaluate(() => localStorage.getItem("td_theme"))).toBe("light");
  // Persists across navigation and reload, applied before first paint.
  await page.locator('[data-nav="radar"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  // Every page renders in light mode; the keyboard shortcut switches back.
  for (const id of ["overview", "radar", "analyst", "signals", "lab", "participation", "portfolio", "analytics", "history", "settings"]) {
    await page.locator(`[data-nav="${id}"]`).click();
    await expect(page.locator(".page h1")).toBeVisible();
  }
  await page.locator('[data-seg="stTheme"] [data-v="dark"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.keyboard.press("t");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(errors).toEqual([]);
});
