const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));

function evidenceRows(items, marker, className) {
  if (!items.length) return '<span class="analyst-empty">None recorded.</span>';
  return items.map(item => '<span class="' + className + '"><i>' + marker + '</i>'
    + escapeHtml(item.claim || "Evidence recorded.")
    + (item.source_field ? '<small>' + escapeHtml(item.source_field) + ': '
      + escapeHtml(item.source_value == null ? "unavailable" : JSON.stringify(item.source_value))
      + '</small>' : '') + '</span>').join("");
}

export function renderAnalystEvidence(analysis) {
  const supporting = analysis?.confirmations || [];
  const conflicts = analysis?.conflicts || [];
  const missing = analysis?.missing_confirmations || [];
  const unavailable = missing.filter(item => item.category === "availability" || item.source_value == null);
  const gaps = missing.filter(item => !unavailable.includes(item));
  return '<div class="analyst-evidence">'
    + '<section><b>SUPPORTING EVIDENCE</b>'
    + evidenceRows(supporting, '✓', 'analyst-support') + '</section>'
    + '<section><b>CONFLICTS</b>'
    + evidenceRows(conflicts, '⚠', 'analyst-conflict') + '</section>'
    + '<section><b>UNAVAILABLE EVIDENCE</b>'
    + evidenceRows(unavailable, '•', 'analyst-unavailable') + '</section>'
    + (gaps.length ? '<section><b>CONFIRMATION GAPS</b>'
      + evidenceRows(gaps, '•', 'analyst-gap') + '</section>' : '')
    + '</div>';
}

export function confirmationDisplay(event, currentMarket, latestSnapshot) {
  // A persisted snapshot can show that an event was once confirmed, but only
  // the current radar result can establish that it still passes validation.
  const currentValid = currentMarket?.strategy_valid === true;
  const currentState = currentMarket?.state || latestSnapshot?.lifecycle_state || "UNKNOWN";
  return {
    hasConfirmationEvent: Boolean(event?.confirmation_event_id || event?.record_type === "setup_confirmation"),
    currentlyConfirmed: Boolean(event && currentValid),
    label: event && currentValid ? "CURRENTLY CONFIRMED" : "HISTORICAL / RECENT CONFIRMATION",
    currentState,
    currentLifecycle: currentMarket?.lifecycle_state || latestSnapshot?.lifecycle_state || "UNKNOWN",
  };
}

export function freshnessLabel(dataQuality, dataFreshness) {
  const flags = dataQuality?.flags || [];
  if (flags.includes("FUTURE_SOURCE_TIMESTAMP")) return "SOURCE TIMESTAMP UNTRUSTED · AHEAD OF OBSERVATION";
  const age = dataFreshness?.source_age_seconds ?? dataQuality?.source_age_seconds;
  return age == null ? "FRESHNESS UNAVAILABLE" : Number(age).toFixed(0) + "s old";
}
