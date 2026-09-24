import test from "node:test";
import assert from "node:assert/strict";
import {comparisonRows, evidenceModel, evidencePanel, labReportPanel, labStrategies} from "../src/garden/strategyLab.mjs";

const block = (id, mode, over = {}) => ({strategy_id: id, mode, version: id === "trendline" ? "trendline-first-v3" : "sr-levels-v1",
  setups: {total: 5, open: 2, closed: 3, by_state: {DETECTED: 0, DEVELOPING: 1, CONFIRMING: 1, CONFIRMED: 0, ACTIVE: 0, INVALIDATED: 2, EXPIRED: 1, RESOLVED: 0}},
  confirmations: 2, outcomes: {pending: 1, unverified: 1, verified_target: 0, verified_stop: 0, verified_other: 0},
  win_rate: null, win_rate_note: "Not shown: 0 verified target/stop outcomes (needs 30).",
  by_instrument: {XAUUSD: {setups: 5, confirmed: 2, pending: 1, unverified: 1, verified_target: 0, verified_stop: 0, verified_other: 0}},
  by_direction: {}, by_timeframe: {}, by_setup_type: {}, recent: [], ...over});
const REPORT = {strategies: [block("trendline", "LIVE"), block("support_resistance", "SHADOW", {setups: {total: 3, open: 3, closed: 0,
  by_state: {DETECTED: 0, DEVELOPING: 2, CONFIRMING: 0, CONFIRMED: 1, ACTIVE: 0, INVALIDATED: 0, EXPIRED: 0, RESOLVED: 0}}, confirmations: 1,
  recent: [{setup_id: "s1", symbol: "XAUUSD", direction: "LONG", setup_type: "SR_BOUNCE", lifecycle_state: "CONFIRMED", confirmed: true, outcome: "pending",
    last_observed_at: "2026-09-24T12:00:00Z"}]}), block("smc", "UNREGISTERED", {setups: {total: 0, open: 0, closed: 0, by_state: {}}})],
  comparison_note: "Strategies are measured separately and never combined.", outcome_rules: "Pending and unverified never count."};

test("the comparison keeps one column per strategy and withholds an unsupported win rate", () => {
  assert.deepEqual(labStrategies(REPORT).map(s => s.strategy_id), ["trendline", "support_resistance"]);
  const {strategies, rows} = comparisonRows(REPORT);
  assert.deepEqual(strategies.map(s => [s.tag, s.mode]), [["TRENDLINE", "LIVE"], ["S/R", "SHADOW"]]);
  const row = label => rows.find(r => r.label === label).values;
  assert.deepEqual(row("Setups recorded"), [5, 3]);
  assert.deepEqual(row("Confirmed (open)"), [0, 1]);
  assert.deepEqual(row("Confirmations"), [2, 1]);
  assert.deepEqual(row("Outcome pending"), [1, 1]);
  assert.deepEqual(row("Verified target hit"), [0, 0]);
  assert.deepEqual(row("Win rate (verified target vs stop)"), [null, null]);
  const html = labReportPanel(REPORT);
  assert.match(html, /S\/R <span class="gd-shadow-badge">SHADOW<\/span>/);
  assert.match(html, /needs 30/);
  assert.doesNotMatch(html, /%<\/td>/, "no win rate without enough verified outcomes");
  assert.match(html, /data-lab-inspect="s1"/);
  assert.match(html, /data-lab-strategy="support_resistance" aria-pressed="true"/);
  assert.match(labReportPanel(null), /unavailable/);
});

test("the evidence inspector shows stored strategy calculations and never counts unverified outcomes", () => {
  const evidence = {family: "SR_BOUNCE", level: {type: "SUPPORT", price: 99.66, zone_low: 99.2, zone_high: 100.1, reactions: 28, strength: 43,
      reactions_by_timeframe: {M15: 13, H1: 15}, higher_timeframe_reactions: 0, higher_timeframe_confluence: false, role_reversal: false},
    touch: {touched: true, bars_ago: 1, clean_test: true, approach_atr_h1: 1.6}, rejection: {confirmed: true, close_position: 0.94},
    confirmation: {rules: {touched: true, clean_test: true, rejection: true, min_rr: true}, passed: true},
    plan: {entry: 101.6, stop: 98.75, target: 109.89, rr: 2.91, min_rr: 1.5}};
  const detail = {setup_id: "s1", snapshots: [{record_type: "setup_snapshot", observation_id: "o1", symbol: "XAUUSD", direction: "LONG",
      strategy_id: "support_resistance", strategy_version: "sr-levels-v1", shadow: true, observed_at: "2026-09-24T12:00:00Z", strategy_evidence: evidence}],
    lifecycle_events: [{to_state: "CONFIRMED", reason_code: "FIRST_DETECTION", occurred_at: "2026-09-24T12:00:00Z"}],
    confirmation_events: [{observation_id: "o1", confirmed_at: "2026-09-24T12:00:00Z"}],
    market_outcomes: [{observation_id: "o1", horizon: "4h", label: "WIN"}]};
  const model = evidenceModel(detail);
  assert.equal(model.basis, "confirmation snapshot");
  assert.deepEqual([model.level.type, model.level.reactions, model.level.htf, model.plan.rr], ["SUPPORT", 28, false, 2.91]);
  assert.deepEqual(model.outcomes, [{horizon: "4h", label: "WIN", verified: false}]);
  const html = evidencePanel(model);
  assert.match(html, /SHADOW/);
  assert.match(html, /SUPPORT 99\.66/);
  assert.match(html, /M15 13 · H1 15/);
  assert.match(html, /no H4\/D1 reaction/);
  assert.match(html, /✓ clean_test/);
  assert.match(html, /2\.91 \(min 1\.5\)/);
  assert.match(html, /4h: unverified — not counted/);
  assert.match(html, /not a generated explanation/);
  const trendline = evidenceModel({...detail, snapshots: [{...detail.snapshots[0], strategy_id: "trendline", shadow: undefined, strategy_evidence: {}}]});
  assert.match(evidencePanel(trendline), /no structured strategy evidence/);
  assert.equal(evidenceModel({snapshots: []}), null);
});
