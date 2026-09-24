import test from "node:test";
import assert from "node:assert/strict";
import {archiveEntry, archiveSummary, isValidatedOutcome, outcomeR} from "../src/garden/gardenModel.mjs";

const verified = (over = {}) => ({setup_id: "s1", observation_id: "o1", horizon: "1h", label: "WIN",
  label_definition: "target-invalidation-first-v1", timestamp_quality: "VERIFIED", data_quality: {timestamp_quality: "VERIFIED"},
  outcome_time_validity: "OUTCOME_TIME_VALID", outcome_time_validation: {outcome_time_validity: "OUTCOME_TIME_VALID",
    every_candidate_strictly_after_observation: true, candidate_candles_chronological: true}, ...over});
const legacy = (over = {}) => ({setup_id: "s1", observation_id: "o1", horizon: "15m", label: "WIN", label_definition: "target-invalidation-first-v1", ...over});
const confirmedEpisode = (over = {}) => ({setup_id: "s1", symbol: "XAUUSD", direction: "LONG", lifecycle_state: "INVALIDATED",
  confirmation: {observation_id: "o1", confirmed_at: "2026-09-24T09:00:00Z"}, closed_event: {occurred_at: "2026-09-24T12:00:00Z", reason: "x"}, ...over});
const plan = {proposed_entry: 100, reference_price: 100, proposed_stop_loss: 98, proposed_take_profit: 106, invalidation_price: 98};

test("only records passing the backend integrity rules count as validated", () => {
  assert.equal(isValidatedOutcome(verified()), true);
  assert.equal(isValidatedOutcome(legacy()), false, "legacy records lack verified timestamps");
  assert.equal(isValidatedOutcome(verified({timestamp_quality: "UNVERIFIED"})), false);
  assert.equal(isValidatedOutcome(verified({data_quality: {}})), false);
  assert.equal(isValidatedOutcome(verified({outcome_time_validation: {outcome_time_validity: "OUTCOME_TIME_VALID", every_candidate_strictly_after_observation: false, candidate_candles_chronological: true}})), false);
});

test("a setup invalidated before confirmation is not a trade", () => {
  const entry = archiveEntry({setup_id: "s2", symbol: "BTCUSD", direction: "LONG", lifecycle_state: "INVALIDATED"}, [verified({setup_id: "s2"})]);
  assert.equal(entry.kind, "invalidated");
  assert.equal(entry.confirmed, false);
  assert.equal(entry.r, null);
  assert.equal(archiveEntry({setup_id: "s3", lifecycle_state: "EXPIRED"}).kind, "expired");
});

test("confirmed setups only get TARGET/STOP from validated outcomes", () => {
  assert.equal(archiveEntry(confirmedEpisode(), [legacy()]).kind, "unverified");
  assert.equal(archiveEntry(confirmedEpisode(), []).kind, "pending");
  const target = archiveEntry(confirmedEpisode(), [verified({horizon: "4h", label: "WIN"}), verified({horizon: "1h", label: "WIN"})], plan);
  assert.deepEqual([target.kind, target.horizon, target.rText], ["target", "1h", "+3.0R"]);
  const stop = archiveEntry(confirmedEpisode(), [verified({label: "LOSS"})], plan);
  assert.deepEqual([stop.kind, stop.rText], ["stop", "-1.0R"]);
  const noHit = archiveEntry(confirmedEpisode(), [verified({horizon: "15m", label: "NO_HIT"}), verified({horizon: "24h", label: "NO_HIT"})]);
  assert.deepEqual([noHit.kind, noHit.horizon], ["no_hit", "24h"]);
  // outcomes of a different observation of the same setup are not this confirmation's outcome
  assert.equal(archiveEntry(confirmedEpisode(), [verified({observation_id: "other"})]).kind, "pending");
});

test("R is shown only when the labelled barriers are the planned stop and target", () => {
  assert.equal(outcomeR("target", plan), 3);
  assert.equal(outcomeR("stop", plan), -1);
  assert.equal(outcomeR("target", {...plan, invalidation_price: 97}), null, "labelled against a different barrier");
  assert.equal(outcomeR("target", {...plan, proposed_take_profit: null}), null);
  assert.equal(outcomeR("target", null), null);
  assert.equal(outcomeR("no_hit", plan), null);
  assert.equal(archiveEntry(confirmedEpisode(), [verified()]).r, null, "no confirmation snapshot loaded -> no R");
});

test("archive summary never mixes unconfirmed observations into outcomes", () => {
  const entries = [archiveEntry(confirmedEpisode(), [verified()], plan),
    archiveEntry(confirmedEpisode({setup_id: "s9", confirmation: {observation_id: "o9"}}), [legacy({setup_id: "s9", observation_id: "o9"})]),
    archiveEntry({setup_id: "a", lifecycle_state: "INVALIDATED"}), archiveEntry({setup_id: "b", lifecycle_state: "INVALIDATED"}),
    archiveEntry({setup_id: "c", lifecycle_state: "EXPIRED"})];
  assert.deepEqual(archiveSummary(entries), {observed: 5, confirmed: 2, target: 1, stop: 0, verifiedOutcomes: 1, unverified: 1, invalidated: 2, expired: 1});
  assert.equal("winRate" in archiveSummary(entries), false);
});

test("archive panel renders compact rows, honest counts and no win rate", async () => {
  const {archivePanel} = await import("../src/garden/gardenCards.mjs");
  const entries = [archiveEntry(confirmedEpisode(), [legacy()]), archiveEntry({setup_id: "a", symbol: "GER40", direction: "SHORT", lifecycle_state: "EXPIRED"})];
  const html = archivePanel(entries, archiveSummary(entries));
  assert.match(html, /Outcome unverified/);
  assert.match(html, /⏳/);
  assert.match(html, /stay <b>unverified<\/b>/);
  assert.doesNotMatch(html, /win rate/i);
  assert.doesNotMatch(html, /[+-]\d+(\.\d+)?R/, "no R without a verified outcome");
  assert.match(archivePanel(entries, archiveSummary(entries), {filter: "target"}), /No closed setups match/);
});
