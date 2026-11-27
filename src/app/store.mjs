// Engine data store: one polled source per backend endpoint, each with an
// honest status (idle → loading → ok | error). Pages declare which sources they
// need; only those (plus the always-on header sources) are polled.
import { engineFetch } from "../engine.js";

const SOURCES = {
  health:   { path: "/api/health", every: 15000, timeout: 15000 },
  radar:    { path: "/api/market/radar", every: 15000, timeout: 20000 },
  signals:  { path: "/api/strategy-bank/signals?limit=300", every: 60000, timeout: 30000 },
  bank:     { path: "/api/strategy-bank", every: 180000, timeout: 30000 },
  quality:  { path: "/api/signal-quality", every: 300000, timeout: 45000 },
  lab:      { path: "/api/market/strategy-lab", every: 300000, timeout: 90000 },
  perf:     { path: "/api/market/performance", every: 300000, timeout: 90000 },
  scalper:  { path: "/api/scalper/summary", every: 30000, timeout: 15000 },
  fundamentals: { path: "/api/market/fundamentals", every: 600000, timeout: 15000 },
  intel:    { path: "/api/intelligence/overview", every: 60000, timeout: 60000 },
  strategies: { path: "/api/intelligence/strategies", every: 300000, timeout: 60000 },
  participation: { path: "/api/intelligence/participation", every: 300000, timeout: 60000 },
};
const ALWAYS = ["health", "radar", "scalper"];

const state = Object.fromEntries(Object.keys(SOURCES).map(k => [k, { status: "idle", data: null, error: null, updatedAt: 0 }]));
const listeners = new Set();
const timers = new Map();
const inflight = new Map();
let wanted = new Set(ALWAYS);

export const get = key => state[key];
export const data = key => state[key]?.data;
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
const emit = key => { for (const fn of listeners) { try { fn(key, state[key]); } catch (e) { console.error(e); } } };

export async function load(key, { force = false } = {}) {
  const src = SOURCES[key];
  if (!src) throw new Error("Unknown source " + key);
  if (inflight.has(key)) return inflight.get(key);
  const s = state[key];
  if (!force && s.status === "ok" && Date.now() - s.updatedAt < src.every / 2) return s.data;
  if (s.status !== "ok") { s.status = "loading"; emit(key); }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), src.timeout);
  const p = engineFetch(src.path, { signal: controller.signal })
    .then(d => { Object.assign(s, { status: "ok", data: d, error: null, updatedAt: Date.now() }); emit(key); return d; })
    .catch(err => {
      const msg = err?.name === "AbortError" ? "Engine did not respond in time" : err?.status ? `Engine returned ${err.status}` : "Engine unreachable";
      // Keep the last good payload but mark it as errored so pages can say so.
      Object.assign(s, { status: "error", error: msg }); emit(key); return s.data;
    })
    .finally(() => { clearTimeout(timer); inflight.delete(key); });
  inflight.set(key, p);
  return p;
}

function schedule(key) {
  if (timers.has(key)) return;
  load(key);
  timers.set(key, setInterval(() => { if (document.visibilityState !== "hidden") load(key, { force: true }); }, SOURCES[key].every));
}

// Declare the sources the current page needs.
export function need(keys = []) {
  wanted = new Set([...ALWAYS, ...keys]);
  for (const [key, t] of timers) if (!wanted.has(key)) { clearInterval(t); timers.delete(key); }
  for (const key of wanted) schedule(key);
}

export function refreshAll() { for (const key of wanted) load(key, { force: true }); }

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") for (const key of wanted) load(key);
});

// Candle cache (per symbol/timeframe/limit) for charts and sparklines.
const candleCache = new Map();
export async function candles(symbol, timeframe = "M15", limit = 300, { maxAge = 60000 } = {}) {
  const key = symbol + "|" + timeframe + "|" + limit;
  const hit = candleCache.get(key);
  if (hit && Date.now() - hit.at < maxAge) return hit.promise;
  const promise = engineFetch(`/api/market/chart?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}`)
    .then(d => ({ ok: true, ...d, candles: (d.candles || []).filter(c => [c.time, c.open, c.high, c.low, c.close].every(Number.isFinite)) }))
    .catch(err => ({ ok: false, error: err?.status === 503 ? "Market feed unavailable for " + symbol : err?.status === 422 ? symbol + " is not on the engine watchlist" : "Engine unreachable", candles: [] }));
  candleCache.set(key, { at: Date.now(), promise });
  promise.then(r => { if (!r.ok) candleCache.delete(key); });
  return promise;
}

export async function setupAnalysis(setupId) {
  try { return { ok: true, ...(await engineFetch("/api/market/setups/" + encodeURIComponent(setupId) + "/analysis")) }; }
  catch (err) { return { ok: false, error: err?.status === 404 ? "No recorded snapshot for this setup yet" : "Analysis unavailable" }; }
}
export async function setupHistory(setupId) {
  try { return { ok: true, ...(await engineFetch("/api/market/setups/" + encodeURIComponent(setupId) + "/lifecycle")) }; }
  catch { return { ok: false }; }
}

// ICT context + confluence for one instrument (closed broker bars; research only).
const intelCache = new Map();
export async function marketIntel(symbol, { maxAge = 60000 } = {}) {
  const hit = intelCache.get(symbol);
  if (hit && Date.now() - hit.at < maxAge) return hit.promise;
  const promise = engineFetch("/api/intelligence/market?symbol=" + encodeURIComponent(symbol))
    .then(d => d?.ict ? { ok: true, ...d } : { ok: false, error: "The engine returned no ICT context for this instrument" })
    .catch(err => ({ ok: false, error: err?.status === 503 ? "Market feed unavailable" : err?.status === 404 ? "This engine version has no intelligence endpoint yet (restart the engine to load it)" : "Engine unreachable" }));
  intelCache.set(symbol, { at: Date.now(), promise });
  promise.then(r => { if (!r.ok) intelCache.delete(symbol); });
  return promise;
}
