// One strategy identity across TRADeden: the 19-strategy bank and the production strategies.
// Pure functions only (no DOM), unit-tested.
//
// Every signal the dashboard shows has exactly one unified strategy key:
//   - Strategy Bank signals carry their own key (strategy_key);
//   - production setups map onto the bank where the bank links them (trendline BREAK ->
//     Trendline Break & Retest, trendline REVERSAL -> Trendline Bounce, S/R -> Support &
//     Resistance); other production strategies keep a "prod:" key (Trend / Momentum, SMC).
// Validation status is never inferred: a strategy is "validated" only if the backend says so.
// Statistics shown are the backend's RECORDED forward results; backtests stay separate.
import {registerStrategyNames, strategyIdOf} from "./strategyModel.mjs";

// Garden sectors: strategies grow in the branch of their family (19+ thin slices would be unreadable).
export const FAMILIES = Object.freeze([
  Object.freeze({id: "trendline", label: "Trendline", color: "#4f86a8"}),
  Object.freeze({id: "levels", label: "Levels & breakouts", color: "#b3843a"}),
  Object.freeze({id: "trend", label: "Trend & momentum", color: "#7c6bbf"}),
  Object.freeze({id: "reversion", label: "Reversion", color: "#b46a83"}),
  Object.freeze({id: "smart_money", label: "Smart money", color: "#4f9a83"}),
]);
export const OTHER_FAMILY = Object.freeze({id: "other", label: "Other", color: "#8fa396"});

// key: [name, short tag, family, kind]. kind: "bank" (bank scanner), "linked" (production
// strategy the bank links), "production" (production only), "unsupported".
const TABLE = {
  trendline_break_retest: ["Trendline Break & Retest", "TL RETEST", "trendline", "linked"],
  trendline_bounce: ["Trendline Bounce", "TL BOUNCE", "trendline", "linked"],
  support_resistance: ["Support & Resistance", "S/R", "levels", "linked"],
  breakout: ["Breakout Trading", "BREAKOUT", "levels", "bank"],
  ema_crossover: ["EMA Crossover", "EMA CROSS", "trend", "bank"],
  ema_pullback: ["EMA Pullback", "EMA PULLBACK", "trend", "bank"],
  rsi_divergence: ["RSI Divergence", "RSI DIV", "reversion", "bank"],
  macd_momentum: ["MACD Momentum", "MACD", "trend", "bank"],
  bollinger_reversion: ["Bollinger Band Mean Reversion", "BB REVERSION", "reversion", "bank"],
  donchian: ["Donchian Channel Breakout", "DONCHIAN", "levels", "bank"],
  london_breakout: ["London Session Breakout", "LONDON BO", "levels", "bank"],
  opening_range_breakout: ["Opening Range Breakout", "ORB", "levels", "bank"],
  vwap_reversion: ["VWAP Reversion", "VWAP", "reversion", "unsupported"],
  liquidity_sweep: ["Liquidity Sweep", "SWEEP", "smart_money", "bank"],
  fair_value_gap: ["Fair Value Gap", "FVG", "smart_money", "bank"],
  order_block_retest: ["Order Block Retest", "ORDER BLOCK", "smart_money", "bank"],
  market_structure_break: ["Market Structure Break", "MSB", "smart_money", "bank"],
  inside_bar_breakout: ["Inside Bar Breakout", "INSIDE BAR", "levels", "bank"],
  atr_breakout: ["ATR Volatility Breakout", "ATR BO", "levels", "bank"],
  ichimoku: ["Ichimoku Trend Following", "ICHIMOKU", "trend", "bank"],
  "prod:trend_momentum": ["Trend / Momentum", "TREND/MOM", "trend", "production"],
  "prod:smc": ["Smart Money Concepts", "SMC", "smart_money", "production"],
  "prod:trendline_v5": ["Trendline (context)", "TRENDLINE", "trendline", "production"],
  "prod:trendline": ["Trendline (retired v4)", "TRENDLINE", "trendline", "production"],
};
// Production strategy ids (registry) -> family, for setups without a bank mapping.
const PRODUCTION_FAMILY = {trendline: "trendline", trendline_v5: "trendline", support_resistance: "levels", trend_momentum: "trend", smc: "smart_money"};

registerStrategyNames(Object.entries(TABLE).filter(([key]) => !key.startsWith("prod:")).map(([id, [label, tag]]) => ({id, tag, label})));

const upper = value => String(value ?? "").trim().toUpperCase();

/** The unified strategy key of any row: a bank signal, a production episode or confirmation. */
export function unifiedKey(row) {
  if (row?.strategy_key) return String(row.strategy_key);
  const id = strategyIdOf(row);
  if (TABLE[id]) return id;                          // a bank key used as strategy_id (bank garden rows)
  if (id === "trendline_v5") {
    const family = upper(row?.confirmation?.setup_type || row?.setup_type || row?.setup_family);
    if (family === "BREAK") return "trendline_break_retest";
    if (family === "REVERSAL") return "trendline_bounce";
    return "prod:trendline_v5";
  }
  if (id === "support_resistance") return "support_resistance";
  return "prod:" + id;
}

export function familyOf(key) {
  const entry = TABLE[key];
  const id = entry ? entry[2] : PRODUCTION_FAMILY[String(key).replace(/^prod:/, "")] || null;
  return FAMILIES.find(family => family.id === id) || OTHER_FAMILY;
}

/** Display identity of a unified key (a backend name, when given, wins over the table). */
export function unifiedStrategy(key, name = null) {
  const entry = TABLE[key];
  const family = familyOf(key);
  const label = name || (entry ? entry[0] : String(key).replace(/^prod:/, "").replace(/_/g, " "));
  return {id: key, tag: entry ? entry[1] : label.toUpperCase(), label, family: family.id, familyLabel: family.label,
    color: family.color, kind: entry ? entry[3] : "production"};
}

/** Validation wording. Nothing is called validated unless the backend reports VALIDATED. */
export function validationOf(status) {
  const value = upper(status);
  if (value === "VALIDATED") return {key: "validated", label: "Validated"};
  if (value === "UNSUPPORTED") return {key: "unsupported", label: "Unsupported"};
  if (value === "LINKED" || value === "PRODUCTION") return {key: "unproven", label: "Live · not proven profitable"};
  return {key: "experimental", label: "Experimental · not proven profitable"};
}

/**
 * Strategy selector options, from the backend bank report (and the registry for
 * production-only strategies). Without a report the static table is used.
 */
export function strategyOptions(report, registry = null) {
  const rows = Array.isArray(report?.strategies) ? report.strategies
    : Object.entries(TABLE).filter(([key]) => !key.startsWith("prod:")).map(([key, [name, , , kind]], index) => ({
      key, name, n: index + 1, status: kind === "linked" ? "LINKED" : kind === "unsupported" ? "UNSUPPORTED" : "EXPERIMENTAL"}));
  const option = (key, name, status, extra = {}) => ({key, label: name, status: upper(status), validation: validationOf(status),
    selectable: upper(status) !== "UNSUPPORTED", family: familyOf(key).id, ...extra});
  const bank = rows.filter(row => upper(row.status) === "EXPERIMENTAL" || upper(row.status) === "VALIDATED").map(row => option(row.key, row.name, row.status, {n: row.n}));
  const linked = rows.filter(row => upper(row.status) === "LINKED").map(row => option(row.key, row.name, "LINKED", {n: row.n}));
  const live = new Set((Array.isArray(registry) ? registry : []).filter(item => upper(item?.status) === "LIVE").map(item => String(item.strategy_id)));
  const productionOnly = ["trend_momentum", "smc"].filter(id => live.has(id))
    .map(id => option("prod:" + id, unifiedStrategy("prod:" + id).label, "PRODUCTION"));
  const unsupported = rows.filter(row => upper(row.status) === "UNSUPPORTED").map(row => option(row.key, row.name, "UNSUPPORTED", {n: row.n, reason: row.unsupported_reason || null}));
  return {
    all: {key: "all", label: "All strategies", selectable: true},
    groups: [
      {label: "Strategy bank · experimental", options: bank},
      {label: "Production strategies · live", options: [...linked, ...productionOnly]},
      ...(unsupported.length ? [{label: "Unsupported", options: unsupported}] : []),
    ],
  };
}

export function selectableKeys(options) {
  return new Set(["all", ...options.groups.flatMap(group => group.options.filter(option => option.selectable).map(option => option.key))]);
}

export function matchesUnified(row, filter) {
  return !filter || filter === "all" || unifiedKey(row) === filter;
}

export function filterUnified(rows, filter) {
  return (rows || []).filter(row => matchesUnified(row, filter));
}

/** The production strategy_id behind a unified key (for production-only views), or null for bank strategies. */
export function productionIdOf(key) {
  if (key === "trendline_break_retest" || key === "trendline_bounce") return "trendline_v5";
  if (key === "support_resistance") return "support_resistance";
  return String(key).startsWith("prod:") ? String(key).slice(5) : null;
}

const FINAL = new Set(["TARGET_HIT", "STOP_HIT", "AMBIGUOUS", "NO_HIT", "UNAVAILABLE", "TIME_EXIT"]);
export const isOpenSignal = signal => !FINAL.has(upper(signal?.outcome_status));

/**
 * A recorded bank signal as a Garden row (same shape the cards read): open signals are
 * CONFIRMED (bloomed), finished ones RESOLVED (history). Levels are the confirmed plan.
 */
export function bankGardenRow(signal, opportunities = {}) {
  const open = isOpenSignal(signal);
  const plan = {entry: signal.entry, stop_loss: signal.stop_loss, take_profit: signal.take_profit, rr: signal.rr, score: null,
    reason: signal.explanation || null};
  return {
    setup_id: signal.signal_id, bank: true, bankSignal: signal, symbol: signal.symbol, direction: signal.direction,
    strategy_id: signal.strategy_key, strategy_key: signal.strategy_key, strategy_version: null,
    timeframe: signal.timeframe, lifecycle_state: open ? "CONFIRMED" : "RESOLVED",
    confirmation_time: signal.confirmed_at, confirmation: {confirmed_at: signal.confirmed_at},
    confirmed_plan: plan, entry: signal.entry, stop_loss: signal.stop_loss, take_profit: signal.take_profit, rr: signal.rr,
    reason: signal.explanation || null, setup_type: signal.strategy_name, score: null,
    closed_event: open ? null : {occurred_at: signal.outcome_at, reason: signal.outcome_reason || signal.outcome_status},
    confirmedBy: opportunities?.[signal.opportunity_id]?.strategies || [signal.strategy_name],
  };
}

const OUTCOME_KIND = {TARGET_HIT: "target", STOP_HIT: "stop", AMBIGUOUS: "ambiguous", NO_HIT: "no_hit", UNAVAILABLE: "unverified", TIME_EXIT: "time_exit"};

/** The archive kind of a finished bank signal (its recorded outcome; never inferred). */
export function bankOutcomeKind(signal) {
  return OUTCOME_KIND[upper(signal?.outcome_status)] || "pending";
}

/**
 * Unified header figures from RECORDED data: the bank report's per-strategy forward
 * statistics, today's recorded bank signals and the worker status. null = unavailable.
 */
export function unifiedHeaderModel({report = null, signals = null, registry = null, now = Date.now()} = {}) {
  if (!report) return {available: false};
  const rows = Array.isArray(report.strategies) ? report.strategies : [];
  const count = status => rows.filter(row => upper(row.status) === status).length;
  const live = new Set((Array.isArray(registry) ? registry : []).filter(item => upper(item?.status) === "LIVE").map(item => String(item.strategy_id)));
  const productionOnly = ["trend_momentum", "smc"].filter(id => live.has(id)).length;
  const supported = rows.filter(row => upper(row.status) !== "UNSUPPORTED");
  let resolved = 0, wins = 0;
  for (const row of supported) {
    const n = Number(row.resolved) || 0;
    if (n && row.win_rate != null) { resolved += n; wins += Math.round(Number(row.win_rate) * n); }
  }
  const dayStart = new Date(now); dayStart.setHours(0, 0, 0, 0);
  const list = Array.isArray(signals) ? signals : null;
  const worker = report.worker || {};
  return {
    available: true,
    active: supported.length, experimental: count("EXPERIMENTAL"), linked: count("LINKED"), validated: count("VALIDATED"),
    unsupported: count("UNSUPPORTED"), productionOnly,
    signalsToday: list ? list.filter(signal => Date.parse(signal.confirmed_at) >= dayStart.getTime()).length : null,
    open: list ? list.filter(isOpenSignal).length : null,
    resolved, winRate: resolved ? wins / resolved : null,
    monitoring: worker.enabled ? (worker.running ? "Monitoring" : "Starting") : "Not running",
    alerts: worker.telegram_enabled ? "Telegram on" : "Telegram off",
  };
}
