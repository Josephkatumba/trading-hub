import test from "node:test";
import assert from "node:assert/strict";
import {confirmationDisplay, freshnessLabel, renderAnalystEvidence} from "../src/analystPresentation.mjs";

test("analyst renderer leads with claim text and separates evidence categories", () => {
  const html = renderAnalystEvidence({
    confirmations: [{claim: "Bearish price action supports SHORT.", source_field: "features.price_action_state", source_value: "BEARISH"}],
    conflicts: [{claim: "H1 bullish bias opposes SHORT.", source_field: "features.higher_timeframe_bias", source_value: "BULLISH"}],
    missing_confirmations: [{category: "availability", claim: "H4 bias unavailable.", source_field: "features.h4_bias", source_value: null},
      {category: "confirmation", claim: "Trendline gate is false.", source_field: "rule_evidence.trendline_gate", source_value: false}],
  });
  assert.match(html, /SUPPORTING EVIDENCE[\s\S]*Bearish price action supports SHORT/);
  assert.match(html, /CONFLICTS[\s\S]*H1 bullish bias opposes SHORT/);
  assert.match(html, /UNAVAILABLE EVIDENCE[\s\S]*H4 bias unavailable/);
  assert.match(html, /CONFIRMATION GAPS[\s\S]*Trendline gate is false/);
  assert.ok(html.indexOf("Bearish price action supports SHORT") < html.indexOf("features.price_action_state"));
});

test("confirmation event is historical when current strategy_valid is false", () => {
  const event = {record_type: "setup_confirmation", confirmation_event_id: "cnf_1"};
  const state = confirmationDisplay(event,
    {strategy_valid: false, state: "WATCHING", lifecycle_state: "DETECTED"},
    {rule_evidence: {strategy_valid: true}, lifecycle_state: "ACTIVE"});
  assert.equal(state.hasConfirmationEvent, true);
  assert.equal(state.currentlyConfirmed, false);
  assert.equal(state.label, "HISTORICAL / RECENT CONFIRMATION");
  assert.equal(state.currentState, "WATCHING");
  assert.equal(state.currentLifecycle, "DETECTED");
});

test("event is currently confirmed only when current scanner validation is true", () => {
  const state = confirmationDisplay({confirmation_event_id: "cnf_2"},
    {strategy_valid: true, state: "CONFIRMING"}, {});
  assert.equal(state.currentlyConfirmed, true);
  assert.equal(state.label, "CURRENTLY CONFIRMED");
});

test("persisted confirmation snapshot without a current radar market is historical", () => {
  const state = confirmationDisplay({record_type: "setup_confirmation", confirmation_event_id: "cnf_3"},
    null, {rule_evidence: {strategy_valid: true}, lifecycle_state: "ACTIVE"});
  assert.equal(state.currentlyConfirmed, false);
  assert.equal(state.label, "HISTORICAL / RECENT CONFIRMATION");
});

test("future source timestamps are displayed as untrusted", () => {
  assert.match(freshnessLabel({flags: ["FUTURE_SOURCE_TIMESTAMP"]}, {source_age_seconds: -10800}),
    /UNTRUSTED.*AHEAD OF OBSERVATION/);
});
