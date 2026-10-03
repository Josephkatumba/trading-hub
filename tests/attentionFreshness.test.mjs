// Attention freshness: lifecycle says what a setup IS; freshness says how recently
// something meaningful HAPPENED. Freshness orders the Priority Watch; it never
// changes a lifecycle and never hides a live setup.
import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {episodeEventTime, freshnessOf, priorityWatchSlots, rankMarkets, trackScanEvents} from "../src/garden/priorityWatch.mjs";
import {eventAge, priorityWatch} from "../src/garden/gardenCards.mjs";

const REGISTRY = [{strategy_id: "trendline", status: "LIVE"}, {strategy_id: "support_resistance", status: "LIVE"}, {strategy_id: "trend_momentum", status: "LIVE"}];
const NOW = Date.parse("2026-09-25T12:00:00Z");
const ago = minutes => new Date(NOW - minutes * 60000).toISOString();
const scan = (strategy_id, state, direction = null, extra = {}) => ({strategy_id, status: "OK", state, direction, ...extra});
const market = (symbol, strategies = [], extra = {}) => ({symbol, price: 100, change_pct: 0.1, state: "WATCHING", score: 50, strategies, ...extra});
// A recorded episode whose lifecycle events happened `minutes` ago.
const episode = (symbol, state, minutes, extra = {}) => ({setup_id: "stp_" + symbol, symbol, lifecycle_state: state, strategy_id: "trendline", direction: "LONG", score: 70,
  detected_at: ago(minutes + 30), lifecycle_events: [{to_state: "DETECTED", occurred_at: ago(minutes + 30)}, {to_state: state, occurred_at: ago(minutes)}], ...extra});
const rank = (markets, rows = [], options = {}) => rankMarkets(markets, rows, REGISTRY, {now: NOW, ...options});
const symbols = ranked => ranked.map(entry => entry.symbol);

test("freshness bands: 0-15m very fresh, 15-60m fresh, 1-4h recent, 4h+ or unknown stale", () => {
  const band = minutes => freshnessOf(NOW - minutes * 60000, NOW).key;
  assert.deepEqual([band(0), band(14), band(15), band(59), band(60), band(239), band(240), band(4000)],
    ["very-fresh", "very-fresh", "fresh", "fresh", "recent", "recent", "stale", "stale"]);
  assert.equal(freshnessOf(null, NOW).key, "stale", "no known event time is never presented as fresh");
  assert.deepEqual([eventAge(null), eventAge(20000), eventAge(12 * 60000), eventAge(3 * 3600000), eventAge(72 * 3600000)], [null, "now", "12m", "3h", "3d"]);
});

test("an Active setup stays Active regardless of age", () => {
  const [entry] = rank([market("USDCAD")], [episode("USDCAD", "ACTIVE", 3 * 24 * 60)]);
  assert.equal(entry.lifecycle, "ACTIVE");
  assert.equal(entry.tier, 6);
  assert.equal(entry.freshness, "stale");
});

test("a fresh Developing or Confirming setup outranks a stale Active one", () => {
  const rows = [episode("USDCAD", "ACTIVE", 20 * 60), episode("AUDUSD", "DEVELOPING", 10), episode("XAUUSD", "CONFIRMING", 40)];
  assert.deepEqual(symbols(rank([market("USDCAD"), market("AUDUSD"), market("XAUUSD")], rows)), ["XAUUSD", "AUDUSD", "USDCAD"]);
});

test("the USDCAD day: #1 when it becomes Active, overtaken later, back up on a new event", () => {
  const becameActive = Date.parse("2026-09-25T10:00:00Z");
  const usdcad = extra => ({setup_id: "stp_cad", symbol: "USDCAD", lifecycle_state: "ACTIVE", strategy_id: "trend_momentum", direction: "LONG", score: 82,
    detected_at: "2026-09-25T08:00:00Z", lifecycle_events: [{to_state: "ACTIVE", occurred_at: "2026-09-25T10:00:00Z"}], ...extra});
  const gold = at => ({setup_id: "stp_xau", symbol: "XAUUSD", lifecycle_state: "CONFIRMING", strategy_id: "support_resistance", direction: "SHORT", score: 60,
    detected_at: at, lifecycle_events: [{to_state: "CONFIRMING", occurred_at: at}]});
  const markets = [market("USDCAD"), market("XAUUSD")];
  const at = (time, rows) => symbols(rankMarkets(markets, rows, REGISTRY, {now: Date.parse(time)}));
  assert.deepEqual(at("2026-09-25T10:00:30Z", [usdcad()]), ["USDCAD", "XAUUSD"]);
  assert.deepEqual(at("2026-09-25T10:30:00Z", [usdcad(), gold("2026-09-25T06:00:00Z")]), ["USDCAD", "XAUUSD"], "still first at 10:30");
  assert.deepEqual(at("2026-09-25T15:00:00Z", [usdcad(), gold("2026-09-25T14:50:00Z")]), ["XAUUSD", "USDCAD"], "fresh Gold setup moves above by 3 PM");
  assert.deepEqual(at("2026-09-26T09:00:00Z", [usdcad(), gold("2026-09-26T08:30:00Z")]), ["XAUUSD", "USDCAD"], "next morning: still Active, not automatically first");
  // A new meaningful event on USDCAD at 09:15 resets its freshness.
  const renewed = usdcad({lifecycle_events: [{to_state: "ACTIVE", occurred_at: new Date(becameActive).toISOString()}, {to_state: "ACTIVE", occurred_at: "2026-09-26T09:15:00Z"}]});
  const next = rankMarkets(markets, [renewed, gold("2026-09-26T08:30:00Z")], REGISTRY, {now: Date.parse("2026-09-26T09:20:00Z")});
  assert.deepEqual(symbols(next), ["USDCAD", "XAUUSD"]);
  assert.equal(next[0].freshness, "very-fresh");
  assert.equal(next[0].lifecycle, "ACTIVE");
});

test("observed_at (every scan) is not a meaningful event; lifecycle, confirmation and close times are", () => {
  const row = {detected_at: ago(600), observed_at: ago(0), lifecycle_events: [{occurred_at: ago(500)}], confirmation: {confirmed_at: ago(400)}};
  assert.equal(episodeEventTime(row), NOW - 400 * 60000);
  assert.equal(episodeEventTime({...row, closed_event: {occurred_at: ago(5)}}), NOW - 5 * 60000);
  const [entry] = rank([market("USDCAD")], [episode("USDCAD", "ACTIVE", 600, {observed_at: ago(0)})]);
  assert.equal(entry.freshness, "stale");
});

test("stale Active setups never disappear: they still outrank watching and closed markets", () => {
  const rows = [episode("USDCAD", "ACTIVE", 3 * 24 * 60)];
  const markets = [market("USDCAD"), market("EURJPY", [scan("trendline", "WATCHING", "LONG")], {score: 99}), market("CADJPY", [], {lifecycle_state: "INVALIDATED"})];
  assert.deepEqual(symbols(rank(markets, rows)), ["USDCAD", "EURJPY", "CADJPY"]);
  // With nothing fresher around, an old Active setup still takes a top-three slot.
  const slots = priorityWatchSlots(rank([...markets, market("XAUUSD"), market("NZDUSD")], rows));
  assert.equal(slots.priority[0].symbol, "USDCAD");
});

test("live scan changes are dated only when seen changing and holding; scores and flickers are not events", () => {
  const scanned = (state, direction = "SHORT", score = 60) => [market("GBPUSD", [scan("support_resistance", state, direction, {score})])];
  const key = "GBPUSD|support_resistance";
  const step = (memory, markets, minute) => trackScanEvents(memory, markets, REGISTRY, NOW + minute * 60000);
  const first = step(null, scanned("DEVELOPING"), 0);
  assert.equal(first.get(key).since, null, "already present on the first scan: start unknown");
  const scored = step(first, scanned("DEVELOPING", "SHORT", 75), 1);
  assert.equal(scored.get(key).since, null, "a score move is not an event");
  // A one-scan flicker (CONFIRMING, then back to DEVELOPING) never resets attention.
  const blip = step(scored, scanned("CONFIRMING"), 2);
  const back = step(blip, scanned("DEVELOPING"), 3);
  assert.equal(back.get(key).since, null);
  // A change that holds for two scans counts, dated to the scan where it first appeared.
  const changed = step(step(back, scanned("CONFIRMING"), 4), scanned("CONFIRMING"), 5);
  assert.equal(changed.get(key).since, NOW + 4 * 60000);
  const flipped = step(step(changed, scanned("CONFIRMING", "LONG"), 6), scanned("CONFIRMING", "LONG"), 7);
  assert.equal(flipped.get(key).since, NOW + 6 * 60000, "a direction change is an event");
  // That freshly changed scan state now outranks a stale Active setup.
  const ranked = rankMarkets([market("USDCAD"), ...scanned("CONFIRMING")], [episode("USDCAD", "ACTIVE", 2000)], REGISTRY, {now: NOW + 5 * 60000, scanEvents: changed});
  assert.deepEqual(symbols(ranked), ["GBPUSD", "USDCAD"]);
  assert.equal(ranked[0].basis, "scan");
});

test("four slots with freshness: pure attention top 3, Core in slot 4, no duplicates, exactly four rows", () => {
  const rows = [episode("USDCAD", "ACTIVE", 3000), episode("AUDUSD", "DEVELOPING", 5), episode("XAUUSD", "CONFIRMING", 20), episode("NZDUSD", "DETECTED", 90)];
  const markets = ["USDCAD", "AUDUSD", "XAUUSD", "NZDUSD", "BTCUSD", "EURJPY"].map(s => market(s));
  const slots = priorityWatchSlots(rank(markets, rows));
  assert.deepEqual(slots.priority.map(e => e.symbol), ["XAUUSD", "AUDUSD", "NZDUSD"], "XAUUSD is core but ranks naturally in the top 3");
  assert.equal(slots.core.symbol, "BTCUSD", "slot 4 is the next core market, not XAUUSD again");
  const shown = [...slots.priority, slots.core].map(e => e.symbol);
  assert.equal(new Set(shown).size, 4);
  const html = priorityWatch(slots);
  assert.equal((html.match(/class="gd-pw-row/g) || []).length, 4);
  assert.match(html, /data-symbol="AUDUSD"[^>]*data-fresh="very-fresh"/);
  assert.match(html, /gd-fresh-dot/);
});

test("the compact watch is sized by its rows: no internal scrolling, no fixed height", () => {
  const css = readFileSync(new URL("../src/garden/garden-command.css", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  assert.match(css, /\.gd-command \.gd-pw-list \{[^}]*overflow: visible;/);
  assert.match(css, /\.gd-command \.gd-watch \{[^}]*height: auto;[^}]*max-height: none;/);
  assert.match(css, /\.garden-root \.gd-command \.gd-world \{[^}]*min-height: var\(--cc-h\);/, "the Garden stretches to the panel, not the reverse");
});
