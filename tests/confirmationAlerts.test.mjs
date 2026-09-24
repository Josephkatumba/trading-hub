import test from "node:test";
import assert from "node:assert/strict";
import {
  createConfirmationAlertTracker,
  dispatchConfirmationAlerts,
  dispatchTestSound,
  persistedConfirmationEvents,
} from "../src/confirmationAlerts.mjs";
import {CONFIRMATION_CHIME_CONFIG, playConfirmationChime} from "../src/confirmationChime.mjs";

const makeEvent = (setupId, confirmedAt = "2026-09-23T12:00:00.000Z", suffix = "a") => ({
  record_type: "setup_confirmation",
  confirmation_event_id: `event-${suffix}`,
  setup_id: setupId,
  symbol: "EURUSD",
  direction: "LONG",
  setup_type: "TRENDLINE_BREAK",
  score: 78,
  confirmed_at: confirmedAt,
});

test("a new persisted confirmation event triggers one alert", () => {
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-23T11:59:00Z")});
  const event = makeEvent("setup-1");

  assert.deepEqual(tracker.observe([event]), [event]);
});

test("repeated refreshes do not duplicate an alert for the same setup", () => {
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-23T11:59:00Z")});
  const event = makeEvent("setup-1");
  let sounds = 0;
  const poll = () => dispatchConfirmationAlerts(tracker.observe([event]), {
    soundEnabled: true,
    playSound: () => { sounds += 1; },
  });

  poll();
  poll();
  poll();
  assert.equal(sounds, 1);
});

test("same setup identity does not alert again if its event record changes", () => {
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-23T11:59:00Z")});

  assert.equal(tracker.observe([makeEvent("setup-1", undefined, "first")]).length, 1);
  assert.deepEqual(tracker.observe([makeEvent("setup-1", undefined, "replacement")]), []);
});

test("separate new setup IDs produce separate alerts", () => {
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-23T11:59:00Z")});
  const events = [makeEvent("setup-1"), makeEvent("setup-2", undefined, "b")];
  let sounds = 0;

  dispatchConfirmationAlerts(tracker.observe(events), {
    soundEnabled: true,
    playSound: () => { sounds += 1; },
  });
  assert.equal(sounds, 2);
});

test("sound-disabled confirmation dispatch shows the event without playing sound", () => {
  let sounds = 0;
  let notices = 0;
  dispatchConfirmationAlerts([makeEvent("setup-1")], {
    soundEnabled: false,
    playSound: () => { sounds += 1; },
    showNotification: () => { notices += 1; },
  });

  assert.equal(sounds, 0);
  assert.equal(notices, 1);
});

test("test sound is independent of confirmation-event tracking", () => {
  const tracker = createConfirmationAlertTracker({startedAt: Date.parse("2026-09-23T11:59:00Z")});
  let sounds = 0;
  dispatchTestSound(() => { sounds += 1; });

  assert.equal(sounds, 1);
  assert.deepEqual(tracker.observe([]), []);
  assert.deepEqual(tracker.observe([makeEvent("setup-1")]).map(event => event.setup_id), ["setup-1"]);
});

test("only persisted confirmation events are used as alert input", () => {
  const performance = {
    daily: [{setups: [makeEvent("setup-1"), {setup_id: "watch-only", strategy_valid: true}]}],
  };

  assert.deepEqual(persistedConfirmationEvents(performance).map(event => event.setup_id), ["setup-1"]);
});

test("confirmation sound is configured as a louder layered cash-register chime", () => {
  const config = CONFIRMATION_CHIME_CONFIG;
  assert.ok(config.durationSeconds >= 0.5 && config.durationSeconds <= 1.0);
  assert.ok(config.peakGain > 0.09 && config.peakGain < 1.0);
  assert.ok(config.notes.length >= 2);
  assert.ok(config.partials.length >= 3);
  assert.ok(config.partials.some(partial => partial.ratio !== 1));

  let oscillatorCount = 0;
  const context = {
    state: "running",
    currentTime: 1,
    destination: {},
    createOscillator() {
      oscillatorCount += 1;
      return {frequency: {setValueAtTime() {}}, connect() {}, start() {}, stop() {}};
    },
    createGain() {
      return {gain: {setValueAtTime() {}, exponentialRampToValueAtTime() {}}, connect() {}};
    },
  };

  assert.equal(playConfirmationChime(context), true);
  assert.equal(oscillatorCount, config.notes.length * config.partials.length);
});
