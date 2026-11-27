// Pure technical indicators computed from real broker candles. Nothing here
// invents data: every function returns null where history is insufficient.

export function ema(values, period) {
  const out = new Array(values.length).fill(null);
  if (!(period > 0) || values.length < period) return out;
  const k = 2 / (period + 1);
  let prev = values.slice(0, period).reduce((s, v) => s + v, 0) / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

// Wilder's RSI.
export function rsi(closes, period = 14) {
  const out = new Array(closes.length).fill(null);
  if (closes.length <= period) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  gain /= period; loss /= period;
  out[period] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gain = (gain * (period - 1) + Math.max(d, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

// Wilder's ATR.
export function atr(candles, period = 14) {
  const out = new Array(candles.length).fill(null);
  if (candles.length <= period) return out;
  const tr = candles.map((c, i) => i === 0 ? c.high - c.low
    : Math.max(c.high - c.low, Math.abs(c.high - candles[i - 1].close), Math.abs(c.low - candles[i - 1].close)));
  let prev = tr.slice(1, period + 1).reduce((s, v) => s + v, 0) / period;
  out[period] = prev;
  for (let i = period + 1; i < candles.length; i++) {
    prev = (prev * (period - 1) + tr[i]) / period;
    out[i] = prev;
  }
  return out;
}

// Swing-pivot support/resistance: pivots with `span` lower highs/higher lows on
// both sides, clustered within `tolerance` (price units). Strength = touches.
export function supportResistance(candles, { span = 3, tolerance, max = 6 } = {}) {
  if (candles.length < span * 2 + 1) return [];
  const atrs = atr(candles, 14).filter(v => v != null);
  const tol = tolerance ?? (atrs.length ? atrs.at(-1) * 0.6 : 0);
  const pivots = [];
  for (let i = span; i < candles.length - span; i++) {
    const c = candles[i];
    let hi = true, lo = true;
    for (let j = 1; j <= span; j++) {
      if (candles[i - j].high >= c.high || candles[i + j].high > c.high) hi = false;
      if (candles[i - j].low <= c.low || candles[i + j].low < c.low) lo = false;
    }
    if (hi) pivots.push({ price: c.high, time: c.time });
    if (lo) pivots.push({ price: c.low, time: c.time });
  }
  const clusters = [];
  for (const p of pivots.sort((a, b) => a.price - b.price)) {
    const last = clusters.at(-1);
    if (last && p.price - last.max <= tol) {
      last.prices.push(p.price); last.max = p.price; last.lastTime = Math.max(last.lastTime, p.time);
    } else clusters.push({ prices: [p.price], max: p.price, lastTime: p.time });
  }
  const close = candles.at(-1).close;
  return clusters
    .map(c => {
      const price = c.prices.reduce((s, v) => s + v, 0) / c.prices.length;
      return { price, touches: c.prices.length, type: price >= close ? "RESISTANCE" : "SUPPORT", lastTime: c.lastTime };
    })
    .sort((a, b) => b.touches - a.touches || b.lastTime - a.lastTime)
    .slice(0, max)
    .sort((a, b) => b.price - a.price);
}

// Percentile rank (0-100) of the last non-null value within the series.
export function percentileRank(series) {
  const vals = series.filter(v => v != null && Number.isFinite(v));
  if (vals.length < 2) return null;
  const last = vals.at(-1);
  return Math.round(vals.filter(v => v <= last).length / vals.length * 100);
}

// Classify volatility from ATR percentile.
export function volatilityRegime(pct) {
  if (pct == null) return "UNKNOWN";
  if (pct >= 80) return "HIGH";
  if (pct <= 25) return "LOW";
  return "NORMAL";
}
