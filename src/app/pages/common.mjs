// Shared page building blocks: live candle chart with indicators, and the
// market / signal detail drawers.
import * as store from "../store.mjs";
import { candleChart, C as chartColors } from "../charts.mjs";
import { supportResistance, atr as atrSeries, percentileRank, volatilityRegime } from "../indicators.mjs";
import { esc, fmt, icon, dir, badge, stageBadge, outcomeBadge, lifecycle, openDrawer, skeleton, empty, tone, seg, stepper } from "../ui.mjs";
import { ictSection } from "./intel.mjs";
import { lifecycleOf, biasOf, atrPct, signalOutcome, signalR, ago, STAGE_INFO } from "../model.mjs";

export const TIMEFRAMES = ["M5", "M15", "H1", "H4", "D1"];

// Chart controls + container. Returns html; call mountChart afterwards.
export function chartControls(prefix, { tf = "M15", rsi = true, atr = false, levels = true } = {}) {
  return `<div class="toolbar">${seg(prefix + "Tf", TIMEFRAMES.map(t => [t, t]), tf)}
   <label class="switch"><input type="checkbox" data-ind="ema" checked>EMA 20/50</label>
   <label class="switch"><input type="checkbox" data-ind="levels" ${levels ? "checked" : ""}>S/R</label>
   <label class="switch"><input type="checkbox" data-ind="rsi" ${rsi ? "checked" : ""}>RSI</label>
   <label class="switch"><input type="checkbox" data-ind="atr" ${atr ? "checked" : ""}>ATR</label>
   <label class="switch"><input type="checkbox" data-ind="plan" checked>Plan levels</label></div>`;
}

// Live chart controller bound to a container + its controls.
export function liveChart(container, controls, { symbol, tf = "M15", plan = null, markers = [], onLevels } = {}) {
  let handle = null, token = 0, state = { symbol, tf, plan, markers };
  const opt = name => controls?.querySelector(`[data-ind="${name}"]`)?.checked ?? true;
  async function draw() {
    const my = ++token;
    handle?.destroy(); handle = null;
    container.innerHTML = `<div class="chart-msg">${skeleton(1, 8)}Loading ${esc(state.symbol)} ${state.tf} broker candles…</div>`;
    const res = await store.candles(state.symbol, state.tf, 300);
    if (my !== token || !container.isConnected) return;
    if (!res.ok || !res.candles.length) { container.innerHTML = `<div class="chart-msg">${icon("info")} ${esc(res.error || "No candles returned")} · chart not drawn</div>`; onLevels?.(null, res); return; }
    container.innerHTML = "";
    const levels = supportResistance(res.candles, { max: 6 });
    onLevels?.(levels, res);
    handle = await candleChart(container, {
      candles: res.candles, symbol: state.symbol, digits: res.digits,
      emas: opt("ema") ? [20, 50] : [], levels: opt("levels") ? levels : [],
      plan: opt("plan") ? state.plan : null, markers: state.markers,
      showRSI: opt("rsi"), showATR: opt("atr"),
    });
  }
  controls?.querySelectorAll("[data-ind]").forEach(i => i.onchange = draw);
  controls?.querySelectorAll("[data-seg] button").forEach(b => b.onclick = () => {
    controls.querySelectorAll("[data-seg] button").forEach(x => x.classList.toggle("on", x === b));
    state.tf = b.dataset.v; draw();
  });
  draw();
  return {
    set(next) { Object.assign(state, next); if (next.tf && controls) controls.querySelectorAll("[data-seg] button").forEach(x => x.classList.toggle("on", x.dataset.v === next.tf)); draw(); },
    destroy() { token++; handle?.destroy(); handle = null; },
  };
}

const planOf = m => (m && [m.entry, m.stop_loss, m.take_profit].some(Number.isFinite)) ? { entry: m.entry, stop: m.stop_loss, target: m.take_profit } : null;

// Market detail (Radar / Overview).
export function openMarket(m) {
  if (!m) return;
  const stage = lifecycleOf(m), bias = biasOf(m), vol = atrPct(m);
  const body = openDrawer(`
    <div class="dh"><h2>${esc(m.symbol)}</h2>${dir(m.direction)}${stageBadge(stage)}${badge(bias, bias === "BULLISH" ? "good" : bias === "BEARISH" ? "bad" : "muted")}</div>
    <p class="dsub">${esc(m.setup || "No active setup")} · ${esc(m.stage || "")} · ${esc(m.timeframe || "M15")} · scanned ${ago(m.timestamp)} · source ${esc(m.source || "MT5")}</p>
    <div class="kv">
      <div><span>Price</span><b>${fmt.price(m.price, m.symbol, m.digits)}</b></div>
      <div><span>Change</span><b class="${tone(m.change_pct)}">${fmt.pct(m.change_pct)}</b></div>
      <div><span>Spread</span><b>${fmt.price(m.spread, m.symbol, m.digits)}</b></div>
      <div><span>ATR (M15)</span><b>${fmt.price(m.atr, m.symbol, m.digits)}</b></div>
      <div><span>ATR % price</span><b>${vol == null ? "—" : vol.toFixed(3) + "%"}</b></div>
      <div><span>RSI 14</span><b>${fmt.num(m.rsi, 1)}</b></div>
      <div><span>Score</span><b>${fmt.int(m.score)}</b></div>
      <div><span>HTF bias</span><b>${esc(m.higher_timeframe_bias || "—")}</b></div>
    </div>
    <div class="dsec"><h3>Lifecycle</h3>${stepper(stage === "IDLE" ? "WATCHING" : stage)}<p class="dsub" style="margin-top:10px"><b>${esc((STAGE_INFO[stage] || STAGE_INFO.IDLE).label)}.</b> ${esc((STAGE_INFO[stage] || STAGE_INFO.IDLE).hint)} ${m.trigger ? "Trigger: " + esc(m.trigger) + "." : ""}</p></div>
    <div class="dsec" id="mdIct"><h3 class="ai">${icon("analyst")}ICT market context · research</h3>${skeleton(4)}</div>
    <div class="dsec"><h3>Chart · live broker candles</h3><div id="mdCtl"></div><div class="chart tall" id="mdChart" style="margin-top:8px"></div></div>
    <div class="dsec"><h3>Plan (as recorded by the scanner)</h3>
      ${planOf(m) ? `<div class="kv"><div><span>Entry</span><b>${fmt.price(m.entry, m.symbol, m.digits)}</b></div><div><span>Stop loss</span><b class="down">${fmt.price(m.stop_loss, m.symbol, m.digits)}</b></div><div><span>Take profit</span><b class="up">${fmt.price(m.take_profit, m.symbol, m.digits)}</b></div><div><span>R:R</span><b>${fmt.num(m.rr, 2)}</b></div><div><span>Invalidation</span><b>${fmt.price(m.invalidation_price ?? m.invalidation_hint, m.symbol, m.digits)}</b></div><div><span>Qualified</span><b>${m.trade_qualified ? "Yes" : "No"}</b></div></div>
      <p class="source">${icon("info")}<span>A plan on a non-confirmed stage is a working hypothesis from the scanner, not a signal. ${m.strategy_valid ? "" : "strategy_valid is false for this scan."}</span></p>` : empty("No plan levels recorded")}
    </div>
    <div class="dsec"><h3>Scanner reasoning</h3><p class="prose">${esc(m.reason || "—")}</p><p class="prose" style="margin-top:8px;color:var(--t3)">${esc(m.insight || "")}</p></div>
    <div class="dsec"><h3>Market structure</h3><div class="kv"><div><span>Structure</span><b style="font-size:11.5px">${esc(m.structure || "—")}</b></div><div><span>Momentum</span><b>${esc(m.momentum || "—")}</b></div><div><span>Price action</span><b style="font-size:11.5px">${esc(m.price_action || "—")}</b></div><div><span>Nearest level</span><b>${esc(m.nearest_level_type || "—")} ${fmt.price(m.nearest_level, m.symbol, m.digits)}</b></div><div><span>Session</span><b>${esc(m.session || "—")}</b></div><div><span>Trendline</span><b>${esc(m.trendline_state || "—")}</b></div></div></div>
    <div class="dsec" id="mdAnalysis"><h3>Deterministic analyst</h3>${skeleton(3)}</div>
    <div class="dsec" style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" data-go="analyst">${icon("analyst")}Open in AI Analyst</button><button class="btn ghost" data-go="signals">${icon("signals")}Signals for ${esc(m.symbol)}</button></div>`, { wide: true, onClose: () => chart?.destroy() });
  body.querySelector("#mdCtl").innerHTML = chartControls("md");
  const chart = liveChart(body.querySelector("#mdChart"), body.querySelector("#mdCtl"), { symbol: m.symbol, plan: planOf(m) });
  body.querySelectorAll("[data-go]").forEach(b => b.onclick = () => window.tdGo(b.dataset.go, { symbol: m.symbol }));
  store.marketIntel(m.symbol).then(res => { const el = body.querySelector("#mdIct"); if (el) el.innerHTML = `<h3 class="ai">${icon("analyst")}ICT market context · research</h3>` + ictSection(res, m.symbol, m.digits); });
  if (m.setup_id) store.setupAnalysis(m.setup_id).then(a => { const el = body.querySelector("#mdAnalysis"); if (el) el.innerHTML = "<h3>Deterministic analyst</h3>" + analysisHtml(a); });
  else body.querySelector("#mdAnalysis").innerHTML = "<h3>Deterministic analyst</h3>" + empty("No setup id on this scan");
}

export function analysisHtml(a) {
  if (!a?.ok) return empty(esc(a?.error || "Analysis unavailable"));
  const list = (rows, cls) => rows?.length ? `<ul class="evid ${cls}">${rows.map(r => `<li><span>${esc(r.claim)} <code>${esc(r.source_field)}</code></span></li>`).join("")}</ul>` : `<p class="dsub">None recorded.</p>`;
  return `<p class="prose"><b>${esc(a.classification)}</b> · ${esc(a.summary)}</p>
    <div class="dsec"><h3>Confirmations</h3>${list(a.confirmations, "pos")}</div>
    <div class="dsec"><h3>Conflicts</h3>${list(a.conflicts, "neg")}</div>
    <div class="dsec"><h3>Missing evidence</h3>${list(a.missing_confirmations, "warn")}</div>
    <p class="source">${icon("info")}<span>${esc(a.analyst_version || "")} · every claim cites the recorded snapshot field it came from.</span></p>`;
}

// Signal detail (Signal Centre / Overview).
export function openSignal(s, all = []) {
  if (!s) return;
  const q = s.quality || {}, out = signalOutcome(s);
  const t = Date.parse(s.confirmed_at);
  const sameSym = all.filter(x => x.symbol === s.symbol && x.signal_id !== s.signal_id).slice(0, 6);
  const body = openDrawer(`
    <div class="dh"><h2>${esc(s.symbol)}</h2>${dir(s.direction)}${outcomeBadge(out)}${badge(s.status || "", s.status === "EXPERIMENTAL" ? "warn" : "good")}</div>
    <p class="dsub">${esc(s.strategy_name)} · ${esc(s.timeframe)} · confirmed ${fmt.dt(s.confirmed_at)} UTC (${ago(s.confirmed_at)})</p>
    <div class="kv">
      <div><span>Entry</span><b>${fmt.price(s.entry, s.symbol)}</b></div>
      <div><span>Stop loss</span><b class="down">${fmt.price(s.stop_loss, s.symbol)}</b></div>
      <div><span>Take profit</span><b class="up">${fmt.price(s.take_profit, s.symbol)}</b></div>
      <div><span>R:R</span><b>${fmt.num(s.rr, 2)}</b></div>
      <div><span>Quality</span><b>${q.grade ? esc(q.grade) + " · " + fmt.int(q.score) : "Ungraded"}</b></div>
      <div><span>Outcome</span><b class="${tone(signalR(s))}">${out}${signalR(s) != null ? " · " + fmt.r(signalR(s)) : ""}</b></div>
    </div>
    <p class="source">${icon("info")}<span>${esc(s.r_basis || "R multiples are hypothetical signal outcomes, not executed trades.")}</span></p>
    <div class="dsec"><h3>Chart · ${esc(s.timeframe || "M15")} with recorded plan</h3><div id="sgCtl"></div><div class="chart tall" id="sgChart" style="margin-top:8px"></div></div>
    <div class="dsec"><h3>Rationale</h3><p class="prose">${esc(s.explanation || "—")}</p></div>
    ${s.contradictions?.length ? `<div class="dsec"><h3>Contradictions at confirmation</h3><ul class="evid neg">${s.contradictions.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>` : ""}
    ${q.model_version ? `<div class="dsec"><h3>Signal quality · ${esc(q.model_version)} (${esc(q.mode || "")})</h3>
      <div class="kv"><div><span>Decision</span><b>${esc(q.decision || "—")}</b></div><div><span>Expected R</span><b class="${tone(q.expected_r)}">${fmt.r(q.expected_r, 3)}</b></div><div><span>Regime</span><b>${esc(q.regime || "—")}</b></div><div><span>Stage</span><b>${esc(q.stage || "—")}</b></div></div>
      <p class="dsub" style="margin-top:8px">${esc(q.reason || "")}</p>
      <div class="grid g-12"><div class="c-6"><h3 class="kicker">Supporting</h3><ul class="evid pos">${(q.supporting || []).map(x => `<li>${esc(x)}</li>`).join("") || "<li>None</li>"}</ul></div><div class="c-6"><h3 class="kicker">Against</h3><ul class="evid neg">${(q.against || []).map(x => `<li>${esc(x)}</li>`).join("") || "<li>None</li>"}</ul></div></div></div>` : ""}
    <div class="dsec"><h3>History</h3><ul class="timeline">
      <li><time>${fmt.dt(s.confirmed_at)}</time>Confirmed · ${esc(s.execution_basis || "")}</li>
      ${s.time_exit_at ? `<li><time>${fmt.dt(s.time_exit_at)}</time>Planned time exit</li>` : ""}
      ${s.outcome_at ? `<li class="${out === "WIN" ? "good" : out === "LOSS" ? "bad" : ""}"><time>${fmt.dt(s.outcome_at)}</time>${esc(out)} · ${esc(s.outcome_reason || "")} (${esc(s.outcome_method || "")})</li>` : `<li><time>now</time>Awaiting outcome</li>`}
    </ul></div>
    ${sameSym.length ? `<div class="dsec"><h3>Other ${esc(s.symbol)} signals</h3><div class="tbl-wrap"><table class="tbl"><tbody>${sameSym.map(x => `<tr class="click" data-sig="${esc(x.signal_id)}"><td>${fmt.dt(x.confirmed_at)}</td><td>${dir(x.direction)}</td><td>${esc(x.strategy_name)}</td><td class="r ${tone(signalR(x))}">${fmt.r(signalR(x))}</td><td>${outcomeBadge(signalOutcome(x))}</td></tr>`).join("")}</tbody></table></div></div>` : ""}`, { wide: true, onClose: () => chart?.destroy() });
  body.querySelector("#sgCtl").innerHTML = chartControls("sg", { tf: s.timeframe && ["M5", "M15", "H1", "H4", "D1"].includes(s.timeframe) ? s.timeframe : "M15" });
  const marker = Number.isFinite(t) ? [{ time: Math.floor(t / 1000 / 60) * 60, position: s.direction === "LONG" ? "belowBar" : "aboveBar", color: s.direction === "LONG" ? chartColors().up : chartColors().down, shape: s.direction === "LONG" ? "arrowUp" : "arrowDown", text: "Signal" }] : [];
  const chart = liveChart(body.querySelector("#sgChart"), body.querySelector("#sgCtl"), { symbol: s.symbol, tf: s.timeframe || "M15", plan: { entry: s.entry, stop: s.stop_loss, target: s.take_profit }, markers: alignMarkers(marker, s.timeframe) });
  body.querySelectorAll("[data-sig]").forEach(r => r.onclick = () => openSignal(all.find(x => x.signal_id === r.dataset.sig), all));
}

// Snap marker times to the candle open of the timeframe.
function alignMarkers(markers, tf = "M15") {
  const sec = { M5: 300, M15: 900, H1: 3600, H4: 14400, D1: 86400 }[tf] || 900;
  return markers.map(m => ({ ...m, time: Math.floor(m.time / sec) * sec }));
}

export function volatilityFromCandles(candles) {
  const a = atrSeries(candles, 14);
  const pct = percentileRank(a);
  return { atr: a.filter(v => v != null).at(-1) ?? null, percentile: pct, regime: volatilityRegime(pct) };
}
