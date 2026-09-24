// Local, browser-synthesized trading-floor chime. Peak gains stay below 1.0;
// the short staggered notes create a cash-register-like metallic flourish.
export const CONFIRMATION_CHIME_CONFIG = Object.freeze({
  durationSeconds: 0.82,
  peakGain: 0.62,
  notes: Object.freeze([
    Object.freeze({frequency: 1046.5, offset: 0, duration: 0.62, level: 0.58}),
    Object.freeze({frequency: 1318.5, offset: 0.15, duration: 0.61, level: 0.66}),
    Object.freeze({frequency: 1568.0, offset: 0.29, duration: 0.53, level: 0.72}),
  ]),
  partials: Object.freeze([
    Object.freeze({ratio: 1, level: 0.58}),
    Object.freeze({ratio: 2.76, level: 0.22}),
    Object.freeze({ratio: 5.4, level: 0.09}),
  ]),
});

export function playConfirmationChime(context, startAt = context.currentTime) {
  if (!context || context.state !== "running") return false;
  try {
    for (const note of CONFIRMATION_CHIME_CONFIG.notes) {
      const noteStart = startAt + note.offset;
      for (const partial of CONFIRMATION_CHIME_CONFIG.partials) {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const peak = Math.min(0.95, CONFIRMATION_CHIME_CONFIG.peakGain * note.level * partial.level);
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(note.frequency * partial.ratio, noteStart);
        gain.gain.setValueAtTime(0.0001, noteStart);
        gain.gain.exponentialRampToValueAtTime(peak, noteStart + 0.012);
        gain.gain.exponentialRampToValueAtTime(0.0001, noteStart + note.duration);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start(noteStart);
        oscillator.stop(noteStart + note.duration + 0.01);
      }
    }
    return true;
  } catch (_) {
    return false;
  }
}
