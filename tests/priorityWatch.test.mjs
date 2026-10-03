// Priority Watch: an attention order over scanned markets, never a trade ranking.
import test from "node:test";
import assert from "node:assert/strict";
import {CORE_MARKETS, isCoreMarket, marketName, marketWatchGroups, priorityEntry, priorityWatchSlots, rankMarkets} from "../src/garden/priorityWatch.mjs";
import {marketWatchAll, priorityWatch, priorityWatchRow} from "../src/garden/gardenCards.mjs";

const REGISTRY = [{strategy_id: "trendline", status: "LIVE"}, {strategy_id: "support_resistance", status: "LIVE"}, {strategy_id: "trend_momentum", status: "LIVE"}];
const scan = (strategy_id, state, direction = null, extra = {}) => ({strategy_id, status: "OK", state, direction, ...extra});
const market = (symbol, strategies = [], extra = {}) => ({symbol, price: 100, change_pct: 0.1, state: "WATCHING", score: 50, strategies, ...extra});
const episode = (symbol, lifecycle_state, extra = {}) => ({setup_id: "stp_" + symbol + "_" + lifecycle_state, symbol, lifecycle_state, strategy_id: "trendline", direction: "LONG", score: 60, ...extra});
const order = (markets, rows = []) => rankMarkets(markets, rows, REGISTRY).map(entry => entry.symbol);

test("lifecycle tier decides first: confirmed > confirming > developing > detected > watching > closed > nothing", () => {
  const markets = [
    market("AAA", [scan("trendline", "WATCHING", "LONG")], {score: 99}),
    market("BBB", [scan("trendline", "DEVELOPING", "LONG", {score: 40})]),
    market("CCC", [scan("support_resistance", "CONFIRMING", "SHORT", {score: 30})]),
    market("DDD", [scan("trend_momentum", "WATCHING", "LONG", {confirmed: true, score: 10})]),
    market("EEE", [], {lifecycle_state: "INVALIDATED", score: 95}),
    market("FFF", [], {state: "", score: 99}),
  ];
  assert.deepEqual(order(markets, [episode("GGG", "DETECTED")]).slice(0, 0), []);
  assert.deepEqual(order([...markets, market("GGG")], [episode("GGG", "DETECTED")]), ["DDD", "CCC", "BBB", "GGG", "AAA", "EEE", "FFF"]);
});

test("within a tier: engine score, then strategy agreement, then recency, then symbol", () => {
  const markets = [
    market("LOW", [scan("trendline", "DEVELOPING", "LONG", {score: 60})]),
    market("HIGH", [scan("trendline", "DEVELOPING", "LONG", {score: 80})]),
    market("ONE", [scan("trendline", "DEVELOPING", "LONG", {score: 70})]),
    market("TWO", [scan("trendline", "DEVELOPING", "LONG", {score: 70}), scan("support_resistance", "WATCHING", "LONG")]),
  ];
  assert.deepEqual(order(markets), ["HIGH", "TWO", "ONE", "LOW"]);
  // Both events days old (same freshness band): the more recent event goes first, even against the alphabet.
  const rows = [episode("EARLY", "DEVELOPING", {score: 70, detected_at: "2026-09-20T08:00:00Z"}), episode("LATE", "DEVELOPING", {score: 70, detected_at: "2026-09-20T09:00:00Z"})];
  assert.deepEqual(order([market("EARLY"), market("LATE")], rows), ["LATE", "EARLY"]);
  assert.deepEqual(order([market("ZZZ"), market("AAA")]), ["AAA", "ZZZ"], "fully deterministic");
});

test("a live setup outranks the market's own closed trendline episode (no stale INVALIDATED label)", () => {
  const usdcad = market("USDCAD", [scan("trendline", "WATCHING", "LONG"), scan("trend_momentum", "WATCHING", "LONG")], {lifecycle_state: "INVALIDATED"});
  const entry = priorityEntry(usdcad, [episode("USDCAD", "ACTIVE", {strategy_id: "trend_momentum", score: 82})], REGISTRY);
  assert.equal(entry.lifecycle, "ACTIVE");
  assert.equal(entry.leadStrategy, "trend_momentum");
  assert.equal(entry.score, 82);
  assert.equal(entry.agreement, 2);
  assert.equal(entry.leadKey, "stp_USDCAD_ACTIVE");
  const closed = priorityEntry(market("NAS100", [scan("trendline", "WATCHING", null)], {lifecycle_state: "INVALIDATED"}), [], REGISTRY);
  assert.equal(closed.lifecycle, "INVALIDATED");
});

test("shadow or unregistered strategies never raise a market's priority", () => {
  const registry = [{strategy_id: "trendline", status: "LIVE"}, {strategy_id: "trend_momentum", status: "SHADOW"}];
  const entry = priorityEntry(market("EURUSD", [scan("trendline", "WATCHING"), scan("trend_momentum", "CONFIRMING", "LONG", {confirmed: true})]), [], registry);
  assert.equal(entry.lifecycle, "WATCHING");
});

test("core markets: recognised, named, and never better trades", () => {
  for (const symbol of ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD", "USDJPY", "US500", "GER40", "XAGUSD", "ETHUSD", "NAS100", "US100"]) assert.ok(isCoreMarket(symbol), symbol);
  assert.ok(CORE_MARKETS.includes("NAS100"));
  assert.ok(!isCoreMarket("AUDUSD"));
  assert.equal(marketName("XAUUSD"), "Gold");
  assert.equal(marketName("BTCUSD"), "Bitcoin");
  // A non-core market with a real setup outranks a core market that is merely watching.
  const ranked = rankMarkets([market("XAUUSD", [scan("trendline", "WATCHING", "LONG")], {score: 99}), market("AUDUSD", [scan("support_resistance", "DEVELOPING", "SHORT", {score: 41})])], [], REGISTRY);
  assert.deepEqual(ranked.map(e => e.symbol), ["AUDUSD", "XAUUSD"]);
});

test("four slots: three by priority, then the strongest core market not already shown", () => {
  const markets = [
    market("AUDUSD", [scan("trendline", "DEVELOPING", "LONG", {score: 70})]),
    market("NZDUSD", [scan("support_resistance", "CONFIRMING", "SHORT", {score: 60})]),
    market("USDCAD", [scan("trend_momentum", "DEVELOPING", "LONG", {score: 65})]),
    market("EURJPY", [scan("trendline", "DETECTED", "LONG", {score: 90})]),
    market("BTCUSD", [scan("trendline", "WATCHING")], {score: 71}),
    market("XAUUSD", [scan("trendline", "WATCHING")], {score: 64}),
  ];
  const slots = priorityWatchSlots(rankMarkets(markets, [], REGISTRY));
  assert.deepEqual(slots.priority.map(e => e.symbol), ["NZDUSD", "AUDUSD", "USDCAD"]);
  assert.equal(slots.core.symbol, "BTCUSD");
  // BTC develops: it competes normally, enters the priority slots, and the core slot moves on.
  markets[4] = market("BTCUSD", [scan("trendline", "DEVELOPING", "LONG", {score: 85})]);
  const next = priorityWatchSlots(rankMarkets(markets, [], REGISTRY));
  assert.deepEqual(next.priority.map(e => e.symbol), ["NZDUSD", "BTCUSD", "AUDUSD"]);
  assert.equal(next.core.symbol, "XAUUSD");
  const all = [...next.priority, next.core].map(e => e.symbol);
  assert.equal(new Set(all).size, all.length, "no symbol twice");
  // Without a core market left, the fourth slot is simply the next market.
  const plain = priorityWatchSlots(rankMarkets(markets.filter(m => !isCoreMarket(m.symbol)), [], REGISTRY));
  assert.equal(plain.priority.length, 4);
  assert.equal(plain.core, null);
});

test("the panel renders exactly four rows; core is a badge, not a colour", () => {
  const markets = ["AUDUSD", "NZDUSD", "USDCAD", "EURJPY", "CHFJPY", "BTCUSD"].map((s, i) => market(s, [scan("trendline", i < 5 ? "DEVELOPING" : "WATCHING", i % 2 ? "SHORT" : "LONG", {score: 90 - i})]));
  markets[5] = market("BTCUSD", [scan("trendline", "WATCHING")]);
  const html = priorityWatch(priorityWatchSlots(rankMarkets(markets, [], REGISTRY)), {selectedSymbol: "NZDUSD", entering: new Set(["BTCUSD"])});
  assert.equal((html.match(/class="gd-pw-row/g) || []).length, 4);
  assert.match(html, /⭐ Core<\/span>/);
  assert.match(html, /data-symbol="BTCUSD" data-dir="none"/, "a watching core market with no direction is not green");
  assert.match(html, /BITCOIN|Bitcoin/);
  assert.match(html, /gd-pw-row gd-market-row is-selected" data-symbol="NZDUSD"/);
  assert.match(html, /is-entering is-core" data-symbol="BTCUSD"/);
  assert.match(html, /TRENDLINE <b>▲ BUY<\/b>/);
});

test("full view: Top priority is exactly the top 3; core not duplicated; the rest is Other or Recently closed", () => {
  const markets = [
    market("AUDUSD", [scan("trendline", "DEVELOPING", "LONG", {score: 80})]),
    market("XAUUSD", [scan("trendline", "CONFIRMING", "SHORT", {score: 70})]),       // core, ranked in the top 3
    market("NZDUSD", [scan("support_resistance", "DEVELOPING", "SHORT", {score: 60})]),
    market("CHFJPY", [scan("trendline", "DEVELOPING", "LONG", {score: 55})]),        // a setup, but 4th: not "priority"
    market("BTCUSD", [scan("trendline", "WATCHING")]),                                // core, not in top 3
    market("EURJPY", [scan("trendline", "WATCHING")]),
    market("CADJPY", [], {lifecycle_state: "EXPIRED"}),
    market("GER40", [], {lifecycle_state: "INVALIDATED"}),                            // core and closed: stays with core
  ];
  const ranked = rankMarkets(markets, [], REGISTRY);
  const groups = marketWatchGroups(ranked);
  const names = Object.fromEntries(Object.entries(groups).map(([k, v]) => [k, v.map(e => e.symbol)]));
  assert.deepEqual(names.priority, ["XAUUSD", "AUDUSD", "NZDUSD"]);
  assert.deepEqual(names.priority, priorityWatchSlots(ranked).priority.map(e => e.symbol), "same top 3 as the compact panel");
  assert.deepEqual(names.core, ["BTCUSD", "GER40"]);
  assert.ok(!names.core.includes("XAUUSD"), "a core market already in the top 3 is not repeated");
  assert.deepEqual(names.other, ["CHFJPY", "EURJPY"]);
  assert.deepEqual(names.closed, ["CADJPY"]);
  const all = Object.values(names).flat();
  assert.equal(all.length, markets.length);
  assert.equal(new Set(all).size, markets.length, "every market exactly once");
  const html = marketWatchAll(groups, {total: markets.length});
  assert.equal((html.match(/class="gd-pw-row/g) || []).length, markets.length);
  for (const title of ["🔥 Top priority", "⭐ Core markets", "👁 Other markets", "🍂 Recently closed"]) assert.ok(html.includes(title), title);
  assert.match(html, /not a trade ranking/);
});

test("a live scan state is labelled apart from a recorded lifecycle", () => {
  const fromScan = priorityEntry(market("USDCHF", [scan("support_resistance", "CONFIRMING", "LONG", {score: 60})]), [], REGISTRY);
  const fromRecord = priorityEntry(market("GBPUSD"), [episode("GBPUSD", "CONFIRMING", {score: 60})], REGISTRY);
  const closed = priorityEntry(market("NZDUSD", [], {lifecycle_state: "INVALIDATED"}), [], REGISTRY);
  assert.deepEqual([fromScan.basis, fromRecord.basis, closed.basis], ["scan", "recorded", "recorded"]);
  assert.equal(fromScan.lifecycle, fromRecord.lifecycle, "same state, different source: the ranking treats them alike");
  const row = entry => priorityWatchRow(entry);
  assert.match(row(fromScan), /data-basis="scan"[^>]*><small class="gd-basis">Live scan ·<\/small> 🌿 CONFIRMING/);
  assert.match(row(fromRecord), /data-basis="recorded"[^>]*><small class="gd-basis">Recorded ·<\/small> 🌿 CONFIRMING/);
  assert.match(row(fromScan), /No recorded episode yet/);
  assert.doesNotMatch(row(priorityEntry(market("EURJPY", []), [], REGISTRY)), /gd-basis/, "no setup: no source label");
});

test("conflict is direction-neutral and keeps every strategy's direction visible", () => {
  const disputed = priorityEntry(market("USDCAD", [scan("trendline", "WATCHING", "LONG"), scan("support_resistance", "WATCHING", "SHORT"), scan("trend_momentum", "DEVELOPING", "SHORT", {score: 70})]), [], REGISTRY);
  assert.equal(disputed.conflict, true);
  const html = priorityWatchRow(disputed);
  assert.match(html, /data-symbol="USDCAD" data-dir="conflict"/);
  assert.match(html, /<span class="gd-bias gd-conflict" data-dir="conflict"[^>]*>Conflict<\/span>/);
  assert.doesNotMatch(html, /class="gd-bias" data-dir="(long|short)"/, "never summarised as LONG or SHORT");
  assert.match(html, /TRENDLINE <b>▲ BUY<\/b>/);
  assert.match(html, /S\/R <b>▼ SELL<\/b>/);
  assert.match(html, /TREND\/MOM <b>▼ SELL<\/b>/);
  const agreed = priorityWatchRow(priorityEntry(market("EURUSD", [scan("trendline", "DEVELOPING", "LONG", {score: 70}), scan("support_resistance", "WATCHING", "LONG")]), [], REGISTRY));
  assert.match(agreed, /class="gd-bias" data-dir="long">LONG</);
  assert.doesNotMatch(agreed, /Conflict/);
});

test("a recorded lifecycle is authoritative over the same setup's scan state", () => {
  const m = market("USDCHF", [scan("support_resistance", "CONFIRMING", "LONG", {setup_id: "stp_sr", score: 60})], {lifecycle_state: "INVALIDATED"});
  assert.equal(priorityEntry(m, [], REGISTRY).lifecycle, "CONFIRMING", "unrecorded setup: the scan is all we have");
  const [closed] = rankMarkets([m], [], REGISTRY, {episodes: [{setup_id: "stp_sr", symbol: "USDCHF", lifecycle_state: "INVALIDATED"}]});
  assert.equal(closed.lifecycle, "INVALIDATED");
  const [live] = rankMarkets([m], [episode("USDCHF", "DEVELOPING", {setup_id: "stp_sr", strategy_id: "support_resistance", score: 60})], REGISTRY);
  assert.equal(live.lifecycle, "DEVELOPING");
});
