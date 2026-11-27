// Pure view-model helpers for the TRADEDEN terminal. No DOM, no fetch: these
// turn engine payloads into display rows, and are unit tested.

export const FEATURED = ["XAUUSD", "BTCUSD", "ETHUSD", "NAS100", "US500", "GER40", "GBPJPY"];
export const LIFECYCLE = ["WATCHING", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE"];
const CRYPTO = new Set(["BTCUSD", "ETHUSD"]);

// Lifecycle stage of a radar market. The recorded episode lifecycle (lifecycle_state) is
// authoritative once it has progressed; "DETECTED" only means an episode exists, so the
// scanner's own state decides (a WATCHING market is never shown as DEVELOPING).
// CONFIRMED / ACTIVE come only from the recorded lifecycle, never from a scanner hint.
export function lifecycleOf(market) {
  const life = String(market?.lifecycle_state || "").toUpperCase();
  const state = String(market?.state || "").toUpperCase();
  if (life === "ACTIVE") return "ACTIVE";
  if (life === "CONFIRMED") return "CONFIRMED";
  // Below confirmation the episode record is monotonic (it never steps back), so the
  // scanner's CURRENT state decides: a setup that fell back to watching shows as watching.
  if (state === "CONFIRMING") return "CONFIRMING";
  if (state === "DEVELOPING") return "DEVELOPING";
  if (state.includes("WATCH")) return "WATCHING";
  if (!state) return life === "CONFIRMING" ? "CONFIRMING" : life === "DEVELOPING" ? "DEVELOPING" : life === "DETECTED" ? "WATCHING" : "IDLE";
  return "IDLE";
}
export const isConfirmedStage = st => st === "CONFIRMED" || st === "ACTIVE";
export const STAGE_INFO = {
  WATCHING: { label: "Watching", hint: "Context only: conditions are being monitored, no setup has formed." },
  DEVELOPING: { label: "Developing", hint: "A setup is forming. Not a signal: key conditions are still missing." },
  CONFIRMING: { label: "Confirming", hint: "Awaiting the closed-candle confirmation. Not a signal yet." },
  CONFIRMED: { label: "Confirmed", hint: "All strategy gates passed on a closed candle: a recorded signal." },
  ACTIVE: { label: "Active", hint: "Confirmed and still valid on the latest scan." },
  IDLE: { label: "Idle", hint: "No setup tracked." },
};

// Asset class of an instrument (display grouping).
export function assetClass(symbol) {
  const s = String(symbol || "");
  if (CRYPTO.has(s)) return "Crypto";
  if (/^(XAU|XAG)/.test(s)) return "Metals";
  if (/^(NAS|US5|US3|GER|UK1|JP2|SPX)/.test(s)) return "Indices";
  return "FX";
}

// Signed trend strength in [-1, 1]: EMA20-EMA50 spread in ATR units (1.5 ATR = full scale),
// signed by the scanner's bias. Null when the inputs are missing.
export function trendStrength(m) {
  const e20 = Number(m?.ema20), e50 = Number(m?.ema50), a = Number(m?.atr);
  if (!(Number.isFinite(e20) && Number.isFinite(e50) && a > 0)) return null;
  const v = Math.max(-1, Math.min(1, (e20 - e50) / a / 1.5));
  return Math.round(v * 100) / 100;
}

// Market breadth across radar rows.
export function breadth(markets) {
  const out = { bullish: 0, bearish: 0, neutral: 0, total: 0, stages: Object.fromEntries(LIFECYCLE.map(s => [s, 0])), confirmed: 0 };
  for (const m of markets || []) {
    out.total++;
    const b = biasOf(m);
    out[b === "BULLISH" ? "bullish" : b === "BEARISH" ? "bearish" : "neutral"]++;
    const st = lifecycleOf(m);
    if (st in out.stages) out.stages[st]++;
    if (isConfirmedStage(st)) out.confirmed++;
  }
  return out;
}

// Evidence tiers in rank order (best first) and a stable ranking for the Strategy Lab.
export const TIER_ORDER = ["PRODUCTION", "VALIDATED", "RESEARCH", "EXPERIMENTAL", "SUSPENDED"];
export function rankStrategies(rows) {
  const lo = r => r.historical?.all_periods?.expectancy_ci95?.[0];
  return [...(rows || [])].sort((a, b) =>
    TIER_ORDER.indexOf(a.evidence?.tier) - TIER_ORDER.indexOf(b.evidence?.tier)
    || (Number.isFinite(lo(b)) ? lo(b) : -9) - (Number.isFinite(lo(a)) ? lo(a) : -9)
    || String(a.name).localeCompare(String(b.name)));
}
export const lifecycleIndex = m => LIFECYCLE.indexOf(lifecycleOf(m));

export function biasOf(market) {
  const d = String(market?.direction || "").toUpperCase();
  const b = String(market?.market_bias || "").toUpperCase();
  if (b === "BULLISH" || (!b && d === "LONG")) return "BULLISH";
  if (b === "BEARISH" || (!b && d === "SHORT")) return "BEARISH";
  return "NEUTRAL";
}

// Market Radar filter predicate.
export function radarFilter(filter) {
  return market => {
    switch (filter) {
      case "ALL": return true;
      case "BULLISH": return biasOf(market) === "BULLISH";
      case "BEARISH": return biasOf(market) === "BEARISH";
      default: return lifecycleOf(market) === filter;
    }
  };
}

// Sort: furthest-progressed lifecycle first, then score.
export function radarRank(a, b) {
  return lifecycleIndex(b) - lifecycleIndex(a) || (Number(b.score) || 0) - (Number(a.score) || 0);
}

// Volatility from ATR relative to price, in percent.
export const atrPct = m => (Number(m?.atr) > 0 && Number(m?.price) > 0) ? Number(m.atr) / Number(m.price) * 100 : null;

// Trading sessions in UTC hours [open, close).
export const SESSIONS = [
  { name: "Sydney", open: 21, close: 6 },
  { name: "Tokyo", open: 0, close: 9 },
  { name: "London", open: 7, close: 16 },
  { name: "New York", open: 12, close: 21 },
];
const inWindow = (h, o, c) => o < c ? h >= o && h < c : h >= o || h < c;

// FX week: Sunday 22:00 UTC to Friday 22:00 UTC. Crypto trades continuously.
export function marketStatus(now = new Date()) {
  const day = now.getUTCDay(), h = now.getUTCHours() + now.getUTCMinutes() / 60;
  const fxClosed = day === 6 || (day === 5 && h >= 22) || (day === 0 && h < 22);
  const active = fxClosed ? [] : SESSIONS.filter(s => inWindow(h, s.open, s.close)).map(s => s.name);
  const overlap = active.includes("London") && active.includes("New York");
  return { fxOpen: !fxClosed, active, overlap, label: fxClosed ? "Weekend · FX closed" : overlap ? "London / New York overlap" : active.join(" · ") || "Between sessions" };
}
export const isCrypto = s => CRYPTO.has(s);

// Price formatting by instrument magnitude / reported digits.
export function priceDigits(symbol, price, digits) {
  if (Number.isInteger(digits) && digits >= 0 && digits <= 8) return digits;
  const p = Math.abs(Number(price));
  if (!Number.isFinite(p)) return 2;
  if (p >= 1000) return 2;
  if (p >= 50) return 3;
  return 5;
}

// Signal outcome normalisation for the bank signal record.
export function signalOutcome(sig) {
  const s = String(sig?.outcome_status || "").toUpperCase();
  if (s === "TARGET_HIT") return "WIN";
  if (s === "STOP_HIT") return "LOSS";
  if (s === "TIME_EXIT") return "TIME EXIT";
  if (s === "PENDING" || !s) return "OPEN";
  return s.replace(/_/g, " ");
}

// R multiple of a resolved signal; null while the signal is still open.
export function signalR(sig) {
  const st = String(sig?.outcome_status || "").toUpperCase();
  if (!st || st === "PENDING") return null;
  const r = Number(sig.r_multiple);
  return sig.r_multiple != null && Number.isFinite(r) ? r : null;
}

// Cumulative R curve from resolved signals (chronological). Hypothetical outcomes.
export function rCurve(signals) {
  const rows = signals
    .filter(s => Number.isFinite(Number(s.r_multiple)) && s.outcome_status && s.outcome_status !== "PENDING")
    .map(s => ({ t: Date.parse(s.outcome_at || s.confirmed_at), r: Number(s.r_multiple) }))
    .filter(x => Number.isFinite(x.t))
    .sort((a, b) => a.t - b.t);
  let eq = 0, peak = 0;
  return rows.map(x => { eq += x.r; peak = Math.max(peak, eq); return { t: x.t, r: x.r, equity: eq, drawdown: eq - peak }; });
}

// Summary stats for a list of R results.
export function rStats(values) {
  const v = values.filter(Number.isFinite);
  const wins = v.filter(x => x > 0), losses = v.filter(x => x < 0);
  const gp = wins.reduce((s, x) => s + x, 0), gl = Math.abs(losses.reduce((s, x) => s + x, 0));
  let eq = 0, peak = 0, dd = 0;
  for (const x of v) { eq += x; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); }
  return {
    n: v.length, wins: wins.length, losses: losses.length,
    winRate: v.length ? wins.length / v.length : null,
    expectancy: v.length ? eq / v.length : null,
    profitFactor: gl ? gp / gl : null,
    total: eq, maxDrawdown: dd,
  };
}

// USD equity/drawdown from executed journal trades.
export function tradeCurve(trades) {
  const rows = trades.map(t => ({ t: Date.parse(String(t.time_utc || t.time).replace(" ", "T") + (t.time_utc ? "" : "Z")), pnl: Number(t.pnl) || 0, trade: t }))
    .filter(x => Number.isFinite(x.t)).sort((a, b) => a.t - b.t);
  let eq = 0, peak = 0;
  return rows.map(x => { eq += x.pnl; peak = Math.max(peak, eq); return { ...x, equity: eq, drawdown: eq - peak }; });
}

// Sum of P&L in the trailing window ending at `now`.
export function pnlSince(curve, ms, now = Date.now()) {
  const inWin = curve.filter(x => x.t > now - ms && x.t <= now);
  return { pnl: inWin.reduce((s, x) => s + x.pnl, 0), trades: inWin.length };
}

// Group rows by a key into {key, n, total} sorted by total desc.
export function groupSum(rows, keyFn, valFn) {
  const m = new Map();
  for (const r of rows) {
    const k = keyFn(r); if (k == null) continue;
    const g = m.get(k) || { key: k, n: 0, total: 0, wins: 0 };
    const v = valFn(r); g.n++; g.total += v; if (v > 0) g.wins++;
    m.set(k, g);
  }
  return [...m.values()].sort((a, b) => b.total - a.total);
}

// Day bucket (UTC date string) for time-series bars.
export const dayKey = t => new Date(t).toISOString().slice(0, 10);
export const monthKey = t => new Date(t).toISOString().slice(0, 7);

// Strategy tier from the bank qualification field.
export function strategyTier(q) {
  const s = String(q || "").toUpperCase();
  if (s === "PRODUCTION") return "PRODUCTION";
  if (s.includes("VALIDATED")) return "VALIDATED";
  if (s.includes("UNSUPPORTED")) return "UNSUPPORTED";
  return "EXPERIMENTAL";
}

// Stable, filterable/sortable signal rows.
export function signalRows(signals) {
  return (signals || []).map(s => ({
    id: s.signal_id,
    time: Date.parse(s.confirmed_at),
    symbol: s.symbol,
    direction: s.direction,
    entry: s.entry, stop: s.stop_loss, target: s.take_profit,
    rr: Number(s.rr) || null,
    strategy: s.strategy_name || s.strategy_key,
    strategyKey: s.strategy_key,
    score: s.quality?.score ?? null,
    grade: s.quality?.grade ?? null,
    stage: s.quality?.stage || (s.outcome_status === "PENDING" ? "ACTIVE" : "RESOLVED"),
    outcome: signalOutcome(s),
    r: signalR(s),
    raw: s,
  }));
}

export function sortRows(rows, key, dir = "desc") {
  const m = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = a[key], y = b[key];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * m;
  });
}

// "4m ago" style relative time.
export function ago(iso, now = Date.now()) {
  const t = typeof iso === "number" ? iso : Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}
