export function isPersistedConfirmation(event) {
  // Shadow-mode strategy confirmations are research records, never live alerts
  // (the backend already keeps them out of the live performance setups list).
  return Boolean(event?.setup_id && event?.shadow !== true &&
    (event?.confirmation_event_id || event?.record_type === "setup_confirmation"));
}

export function persistedConfirmationEvents(performance) {
  const groups = [
    ...(Array.isArray(performance?.daily) ? performance.daily : []),
    ...(performance?.summary ? [performance.summary] : []),
  ];
  const bySetup = new Map();
  for (const group of groups) {
    for (const event of group?.setups || []) {
      if (isPersistedConfirmation(event) && !bySetup.has(event.setup_id)) {
        bySetup.set(event.setup_id, event);
      }
    }
  }
  return [...bySetup.values()];
}

export function createConfirmationAlertTracker({
  initialSetupIds = [],
  startedAt = Date.now(),
  onSeenChange = () => {},
} = {}) {
  const seen = new Set(initialSetupIds.filter(Boolean).map(String));
  const startTime = startedAt instanceof Date ? startedAt.getTime() : Number(startedAt);

  return {
    observe(events, now = Date.now()) {
      const newlyDetected = [];
      let changed = false;
      for (const event of events || []) {
        if (!isPersistedConfirmation(event)) continue;
        const setupId = String(event.setup_id);
        if (seen.has(setupId)) continue;
        seen.add(setupId);
        changed = true;
        const confirmationTime = Date.parse(event.confirmed_at || "");
        // Seed older or undated records silently. They predate this alert
        // session and must not replay as fresh confirmations on page load.
        if (Number.isFinite(confirmationTime) && confirmationTime >= startTime) {
          newlyDetected.push(event);
        }
      }
      if (changed) onSeenChange([...seen]);
      return newlyDetected;
    },
    seenSetupIds() {
      return [...seen];
    },
  };
}

export function dispatchConfirmationAlerts(events, {
  soundEnabled = false,
  playSound = () => {},
  showNotification = () => {},
} = {}) {
  for (const event of events || []) {
    showNotification(event);
    if (soundEnabled) playSound(event);
  }
}

// The test action exercises audio only; it is not passed through confirmation
// identity tracking and cannot create a confirmation notification.
export function dispatchTestSound(playSound = () => {}) {
  return playSound({type: "audio_test"});
}
