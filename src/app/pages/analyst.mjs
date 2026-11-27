import * as store from "../store.mjs";
import { esc, fmt, tone, icon, dir, lifecycle, badge, empty, unavailable, skeleton, sourceNote, outcomeBadge, panel } from "../ui.mjs";
import { lifecycleOf, biasOf, radarRank, signalOutcome, signalR, ago, FEATURED } from "../model.mjs";
import { ema, supportResistance } from "../indicators.mjs";
import { chartControls, liveChart, analysisHtml, volatilityFromCandles } from "./common.mjs";
import { structureHtml, dealingHtml, ladderHtml, zonesHtml, setupsHtml, confluenceHtml } from "./intel.mjs";

export const subtitle = "Market intelligence grounded in live engine data";
export const need = ["signals"];

// Build a grounded analysis from the radar row and H1 candles. Every sentence
// is composed from a cited field; nothing is generated without data.
export function analyze(m, h1) {
  const P = v => fmt.price(v, m.symbol, m.digits);
  const out = { cites: [], P };
  const price = Number(m.price);
  const closes = h1?.candles?.map(c => c.close) || [];
  const e20 = ema(closes, 20).at(-1), e50 = ema(closes, 50).at(-1);
  const e20prev = ema(closes, 20).at(-6);
  const h1Trend = e20 == null || e50 == null ? null : e20 > e50 && price > e20 ? "BULLISH" : e20 < e50 && price < e20 ? "BEARISH" : "MIXED";
  const slope = e20 != null && e20prev != null ? (e20 - e20prev) / e20prev * 100 : null;
  const levels = h1?.candles?.length ? supportResistance(h1.candles, { max: 8 }) : [];
  const res = levels.filter(l => l.price > price).sort((a, b) => a.price - b.price);
  const sup = levels.filter(l => l.price < price).sort((a, b) => b.price - a.price);
  const vol = h1?.candles?.length ? volatilityFromCandles(h1.candles) : null;
  const rsiTxt = !Number.isFinite(m.rsi) ? "unavailable" : m.rsi >= 70 ? "overbought" : m.rsi <= 30 ? "oversold" : m.rsi >= 55 ? "firm" : m.rsi <= 45 ? "soft" : "neutral";
  const rel = (v, name) => Number.isFinite(v) ? `${price >= v ? "above" : "below"} ${name} (${P(v)})` : `${name} unavailable`;

  out.summary = `<b>${esc(m.symbol)}</b> trades at <b>${P(price)}</b> (<span class="${tone(m.change_pct)}">${fmt.pct(m.change_pct)}</span> on the session). M15 structure reads <b>${esc(m.structure || "unavailable")}</b>, market bias <b>${esc(m.market_bias || "—")}</b>, momentum <b>${esc(m.momentum || "—")}</b> and the higher-timeframe bias is <b>${esc(m.higher_timeframe_bias || "—")}</b>. RSI(14) is ${fmt.num(m.rsi, 1)} (${rsiTxt}); price is ${rel(m.ema20, "EMA20")} and ${rel(m.ema50, "EMA50")}.`;
  out.cites.push("radar: price, change_pct, structure, market_bias, momentum, higher_timeframe_bias, rsi, ema20, ema50");

  out.trend = h1Trend
    ? `On H1, EMA20 (${P(e20)}) is ${e20 > e50 ? "above" : "below"} EMA50 (${P(e50)}) and price is ${price > e20 ? "above" : "below"} EMA20 — the H1 trend reads <b class="${h1Trend === "BULLISH" ? "up" : h1Trend === "BEARISH" ? "down" : ""}">${h1Trend}</b>${slope != null ? `, with EMA20 ${slope >= 0 ? "rising" : "falling"} ${Math.abs(slope).toFixed(3)}% over 5 bars` : ""}. The M15 scanner bias is ${esc(m.market_bias || "—")}${h1Trend !== "MIXED" && m.market_bias && m.market_bias !== h1Trend ? " — <b>timeframes disagree</b>, which historically lowers follow-through" : h1Trend === m.market_bias ? " — timeframes agree" : ""}.`
    : "H1 candles are unavailable, so the multi-timeframe trend cannot be assessed.";
  if (h1Trend) out.cites.push(`H1 candles (${closes.length}): EMA20/EMA50 computed client-side`);

  const r1 = res[0], r2 = res[1], s1 = sup[0], s2 = sup[1];
  out.levels = { res, sup, r1, s1 };
  out.bull = r1 || s1
    ? `${s1 ? `Holding support at <b>${P(s1.price)}</b>` : "Holding current levels"}${r1 ? ` and closing an H1 candle above resistance <b>${P(r1.price)}</b>` : ""} would open ${r2 ? `<b>${P(r2.price)}</b>` : "the range high"}.${String(m.direction) === "LONG" && Number.isFinite(m.take_profit) ? ` The scanner's long plan targets ${P(m.take_profit)}.` : ""} The bullish case is invalidated by an H1 close below ${s1 ? P(s1.price) : "recent support"}${s2 ? ` (next support ${P(s2.price)})` : ""}.`
    : "No H1 swing levels are available to frame a bullish scenario.";
  out.bear = r1 || s1
    ? `${r1 ? `Rejection at resistance <b>${P(r1.price)}</b>` : "Failure at current levels"}${s1 ? ` and an H1 close below support <b>${P(s1.price)}</b>` : ""} would expose ${s2 ? `<b>${P(s2.price)}</b>` : "the range low"}.${String(m.direction) === "SHORT" && Number.isFinite(m.take_profit) ? ` The scanner's short plan targets ${P(m.take_profit)}.` : ""} The bearish case is invalidated by an H1 close above ${r1 ? P(r1.price) : "recent resistance"}${r2 ? ` (next resistance ${P(r2.price)})` : ""}.`
    : "No H1 swing levels are available to frame a bearish scenario.";
  if (levels.length) out.cites.push(`H1 swing pivots → ${levels.length} clustered S/R levels`);

  out.vol = vol?.atr != null
    ? `H1 ATR(14) is <b>${P(vol.atr)}</b> (${(vol.atr / price * 100).toFixed(2)}% of price), at the <b>${vol.percentile}th percentile</b> of the last ${h1.candles.length} H1 bars — volatility is <b>${vol.regime.toLowerCase()}</b>. M15 ATR from the scanner is ${P(m.atr)}; spread is ${P(m.spread)}${Number.isFinite(m.spread_atr) ? ` (${(m.spread_atr * 100).toFixed(1)}% of ATR)` : ""}.`
    : `M15 ATR from the scanner is ${P(m.atr)}. H1 volatility history is unavailable.`;
  out.volData = vol;

  const st = lifecycleOf(m);
  out.opportunity = st === "IDLE"
    ? "The scanner has no active setup on this instrument."
    : `Scanner setup: <b>${esc(m.setup || "—")}</b> (${esc(m.stage || "")}), ${String(m.direction) === "LONG" ? "long" : "short"} bias, lifecycle <b>${st}</b>, score ${fmt.int(m.score)}. Trigger: ${esc(m.trigger || "—")}.${m.strategy_valid ? "" : " <b>Not a valid signal yet</b> — the strategy gate has not passed."}`;
  out.invalidation = Number.isFinite(m.invalidation_price ?? m.invalidation_hint)
    ? `The current setup is invalidated at <b>${P(m.invalidation_price ?? m.invalidation_hint)}</b>${Number.isFinite(m.stop_loss) ? `; the recorded stop is ${P(m.stop_loss)}` : ""}.`
    : "No invalidation level is recorded for the current scan.";
  out.cites.push("radar: setup, stage, trigger, score, invalidation_price, stop_loss, take_profit");
  return out;
}

// ICT / confluence answers, composed only from the engine's intelligence payload.
const ORDER = ["NONE", "WATCHING", "DEVELOPING", "CONFIRMING", "CONFIRMED"];
export function ictAnswers(intel, P) {
  if (!intel?.ok) return null;
  const ict = intel.ict, c = intel.confluence;
  const pools = (ict.liquidity || []).filter(p => !p.swept && !p.kind.startsWith("SWING") && p.distance_atr != null).sort((a, b) => Math.abs(a.distance_atr) - Math.abs(b.distance_atr));
  const above = pools.filter(p => p.side === "BSL").slice(0, 3), below = pools.filter(p => p.side === "SSL").slice(0, 3);
  const live = (ict.setups || []).filter(s => s.stage !== "NONE").sort((a, b) => ORDER.indexOf(b.stage) - ORDER.indexOf(a.stage));
  const best = live[0];
  const confirmed = live.filter(s => s.stage === "CONFIRMED");
  const dr = ict.dealing_range;
  const out = {};
  out.liquidity = pools.length
    ? `<b>Liquidity map</b> (unswept pools, distance in M15 ATR)<ul>${above.map(p => `<li>Buy-side above: ${esc(p.label)} ${P(p.price)} (+${p.distance_atr.toFixed(1)} ATR)</li>`).join("")}${below.map(p => `<li>Sell-side below: ${esc(p.label)} ${P(p.price)} (${p.distance_atr.toFixed(1)} ATR)</li>`).join("")}</ul>${ict.events?.length ? `Recent: ${ict.events.slice(-2).map(e => esc(e.text)).join("; ")}.` : "No sweep in the last 24 M15 bars."}`
    : "No unswept liquidity pools are identified on the current bars.";
  out.structure = `Structure: M15 <b>${esc(ict.structure.M15.toLowerCase())}</b>, H1 <b>${esc(ict.structure.H1.toLowerCase())}</b>, H4 bias <b>${esc(ict.structure.H4.toLowerCase())}</b>.${dr ? ` Price sits in the H1 <b>${esc(dr.zone.toLowerCase())}</b> (${Math.round(dr.position * 100)}% of the ${P(dr.low)}–${P(dr.high)} range; equilibrium ${P(dr.equilibrium)}).` : ""} Time: ${esc(ict.ny_time)} New York${ict.kill_zone ? `, inside the <b>${esc(ict.kill_zone)}</b>` : ", outside the kill zones"}.`;
  out.confluence = c ? `<b>Confluence: ${esc(c.classification.toLowerCase())}.</b> ${esc(c.explanation)}${c.caveat ? ` <i>${esc(c.caveat)}</i>` : ""}` : "Confluence is unavailable.";
  out.confirmation = best
    ? (confirmed.length
      ? `<b>${confirmed.map(s => esc(s.name)).join(", ")}</b> confirmed on the last closed M15 bar (research only: recorded, never alerted). ${confirmed[0].evidence.map(esc).join("; ")}.`
      : `<b>Nothing is confirmed.</b> Most advanced: ${esc(best.name)}, ${esc(best.stage.toLowerCase())}${best.direction ? (best.direction === "LONG" ? " long" : " short") : ""}. Still required: ${(best.missing || []).map(esc).join("; ") || "a closed-candle confirmation"}.${best.blocked ? ` Currently blocked: ${esc(best.blocked)}.` : ""}`)
    : "No ICT setup is forming, so there is nothing to confirm.";
  const rev = live.filter(s => ["ict_sweep_reversal", "ict_mss", "ict_judas", "ict_sweep_fvg", "ict_ob_reversal"].includes(s.key) && s.stage !== "WATCHING");
  out.reversal = rev.length
    ? `Reversal evidence: ${rev.map(s => `${esc(s.name)} (${esc(s.stage.toLowerCase())}, ${s.direction === "LONG" ? "bullish" : "bearish"}: ${s.evidence.slice(0, 2).map(esc).join("; ")})`).join(". ")}. A reversal is only a hypothesis until a setup reaches Confirmed.`
    : "No reversal setup (sweep, structure shift, Judas swing or order block) is developing on the last closed bar.";
  out.invalidation = live.filter(s => s.invalidation != null).slice(0, 3).map(s => `${esc(s.name)} beyond ${P(s.invalidation)}`).join("; ");
  return out;
}

const INTENTS = [
  [/liquid|sweep|stop hunt|pool|bsl|ssl|equal high|equal low|pdh|pdl/i, (a, x) => x?.liquidity],
  [/confluen|agree|align|together|independent/i, (a, x) => x?.confluence],
  [/confirm|need|missing|wait|trigger/i, (a, x) => x?.confirmation],
  [/revers|turn|exhaust|top|bottom/i, (a, x) => x?.reversal],
  [/ict|structure|premium|discount|kill ?zone|fvg|gap|order block|ote|mss|bos/i, (a, x) => x?.structure],
  [/summary|overview|what.*(happening|going)|tell me/i, a => a.summary],
  [/trend|direction|bias|ema/i, a => a.trend],
  [/bull|long|upside|buy/i, a => "<b>Bullish scenario.</b> " + a.bull],
  [/bear|short|downside|sell/i, a => "<b>Bearish scenario.</b> " + a.bear],
  [/support|resistance|level|s\/r|key/i, a => levelText(a)],
  [/vol|atr|range|risk/i, a => a.vol],
  [/invalid|stop|wrong/i, (a, x) => a.invalidation + (x?.invalidation ? `<br>ICT setups invalidate: ${x.invalidation}.` : "")],
  [/setup|signal|opportunit|trade|entry/i, a => a.opportunity],
];
const levelText = a => {
  const { res, sup } = a.levels;
  if (!res.length && !sup.length) return "No H1 swing levels are available.";
  return `<b>Key H1 levels</b><ul>${res.slice(0, 3).reverse().map(l => `<li>Resistance ${a.P(l.price)} · ${l.touches} touch${l.touches > 1 ? "es" : ""}</li>`).join("")}${sup.slice(0, 3).map(l => `<li>Support ${a.P(l.price)} · ${l.touches} touch${l.touches > 1 ? "es" : ""}</li>`).join("")}</ul>`;
};

export function mount(root, { params }) {
  let symbol = params.symbol || sessionStorage.getItem("td_an_sym") || "XAUUSD", chart = null, current = null, h1 = null, intel = null, ict = null, token = 0;
  const chatLog = [];
  root.innerHTML = `
    <div class="ph"><div><h1>AI Analyst</h1><p>Structured market intelligence per instrument: summary, scenarios, trend, levels, volatility and invalidation — each composed from live scanner fields and broker candles, with sources cited.</p></div>
      <div class="ph-a"><span class="chip ai" title="No language model is connected. The analyst composes answers from engine data with fixed rules and cites them.">${icon("analyst")}Evidence-based · rule-composed · no LLM</span></div></div>
    <div class="an-layout">
      <section class="panel flush"><header class="panel-h"><div><span class="kicker">Instruments</span><h2>Watchlist</h2></div></header><div class="sym-list" id="anSyms"></div></section>
      <div id="anMain" style="min-width:0;display:flex;flex-direction:column;gap:12px"></div>
      <section class="panel flush an-chat ai-panel"><header class="panel-h"><div><span class="kicker">Conversation</span><h2>Ask the analyst</h2></div><button class="btn sm ghost" id="anClear">Clear</button></header>
        <div class="chat"><div class="chat-log" id="anLog" aria-live="polite"></div>
        <div class="chat-sugg">${["Summary", "Liquidity levels", "Confluence", "What confirms it?", "Reversal risk", "Trend analysis", "Key levels", "Bullish scenario", "Bearish scenario", "Invalidation"].map(s => `<button data-ask="${s}">${s}</button>`).join("")}</div>
        <form class="chat-in" id="anForm"><input id="anIn" placeholder="Ask about ${esc(symbol)}…" autocomplete="off" aria-label="Question"><button class="btn primary" aria-label="Send">${icon("send")}</button></form></div></section>
    </div>`;
  const $ = id => root.querySelector("#" + id);
  const market = () => (store.data("radar")?.markets || []).find(m => m.symbol === symbol);

  function drawSyms() {
    const ms = [...(store.data("radar")?.markets || [])].sort((a, b) => (FEATURED.includes(b.symbol) - FEATURED.includes(a.symbol)) || radarRank(a, b));
    if (!ms.length) { $("anSyms").innerHTML = store.get("radar").status === "error" ? unavailable("Watchlist", store.get("radar").error) : skeleton(6); return; }
    $("anSyms").innerHTML = ms.map(m => `<button class="sym-btn ${m.symbol === symbol ? "on" : ""}" data-sym="${esc(m.symbol)}"><span class="sym">${esc(m.symbol)}</span><span class="mono ${tone(m.change_pct)}" style="font-size:11px">${fmt.pct(m.change_pct)}</span><small>${lifecycle(lifecycleOf(m), true)}<span class="muted" style="font-size:10.5px">${esc(biasOf(m))}</span></small></button>`).join("");
    $("anSyms").querySelectorAll("[data-sym]").forEach(b => b.onclick = () => select(b.dataset.sym));
  }

  function select(sym) {
    symbol = sym; sessionStorage.setItem("td_an_sym", sym);
    $("anIn").placeholder = `Ask about ${sym}…`;
    drawSyms(); chatLog.length = 0; drawMain(true);
  }

  async function drawMain(full) {
    const m = market();
    const my = ++token;
    if (!m) {
      chart?.destroy(); chart = null;
      $("anMain").innerHTML = store.get("radar").data ? `<section class="panel">${unavailable("Analysis for " + symbol, symbol + " is not on the engine watchlist.")}</section>` : store.get("radar").status === "error" ? `<section class="panel">${unavailable("Analysis", "The market engine is unreachable, so no analysis is generated.")}</section>` : `<section class="panel"><div class="panel-b">${skeleton(8)}</div></section>`;
      return;
    }
    if (full || !$("anChart")) {
      chart?.destroy(); chart = null; h1 = null;
      $("anMain").innerHTML = `
        ${panel({ kicker: "Market summary · " + esc(m.symbol), title: `${esc(m.symbol)} <span class="mono" id="anPx" style="margin-left:8px">${fmt.price(m.price, m.symbol, m.digits)}</span>`, actions: `${dir(m.direction)}${badge(biasOf(m), biasOf(m) === "BULLISH" ? "good" : biasOf(m) === "BEARISH" ? "bad" : "muted")}`, body: `<div class="prose" id="anSummary">${skeleton(3)}</div>` })}
        ${panel({ kicker: "Chart", title: "Price, EMA, RSI and levels", body: `<div id="anCtl"></div><div class="chart tall" id="anChart" style="margin-top:8px"></div>` })}
        <section class="panel"><header class="panel-h"><div><span class="kicker">Scenarios</span><h2>Bullish and bearish cases</h2></div></header><div class="panel-b"><div class="scen"><div class="bull"><h4>${icon("up")}Bullish scenario</h4><div class="prose" id="anBull">${skeleton(3)}</div></div><div class="bear"><h4>${icon("down")}Bearish scenario</h4><div class="prose" id="anBear">${skeleton(3)}</div></div></div></div></section>
        <div class="grid g-12"><div class="c-7">${panel({ kicker: "ICT intelligence · research", title: "Structure, premium / discount and liquidity", cls: "ai-panel", body: `<div id="anIct">${skeleton(5)}</div>` })}</div>
          <div class="c-5">${panel({ kicker: "Strategy confluence", title: "Independent evidence", cls: "accent", body: `<div id="anConf">${skeleton(4)}</div>` })}</div>
          <div class="c-12">${panel({ kicker: "Setup progression", title: "ICT setups: what is developing, what is still required, what invalidates it", body: `<div id="anSetups">${skeleton(4)}</div>` })}</div></div>
        <div class="grid g-12"><div class="c-6">${panel({ kicker: "Trend", title: "Trend analysis", body: `<div class="prose" id="anTrend">${skeleton(3)}</div>` })}</div>
          <div class="c-6">${panel({ kicker: "Volatility", title: "Volatility conditions", body: `<div class="prose" id="anVol">${skeleton(3)}</div>` })}</div>
          <div class="c-6">${panel({ kicker: "Levels", title: "Support and resistance (H1)", body: `<div id="anLevels">${skeleton(4)}</div>` })}</div>
          <div class="c-6">${panel({ kicker: "Opportunities", title: "Setup and invalidation", body: `<p class="prose" id="anOpp"></p><p class="prose" id="anInv" style="margin-top:8px"></p><div id="anSigs" style="margin-top:10px"></div>` })}</div>
          <div class="c-12">${panel({ kicker: "Evidence", title: "Deterministic setup analyst", body: `<div id="anEvidence">${skeleton(3)}</div>` })}</div></div>
        <p class="source" id="anCites"></p>`;
      $("anCtl").innerHTML = chartControls("an", { tf: "H1", atr: true });
      chart = liveChart($("anChart"), $("anCtl"), { symbol: m.symbol, tf: "H1", plan: Number.isFinite(m.entry) ? { entry: m.entry, stop: m.stop_loss, target: m.take_profit } : null });
      if (m.setup_id) store.setupAnalysis(m.setup_id).then(a => { if (my === token && $("anEvidence")) $("anEvidence").innerHTML = analysisHtml(a); });
      else $("anEvidence").innerHTML = empty("No setup snapshot recorded for this instrument");
      intel = null; ict = null;
      store.marketIntel(m.symbol).then(res => { if (my !== token) return; intel = res; drawIntel(market()); });
      h1 = await store.candles(m.symbol, "H1", 300, { maxAge: 120000 });
      if (my !== token) return;
    }
    fill(market());
  }

  function fill(m) {
    if (!m || !$("anSummary")) return;
    current = analyze(m, h1?.ok ? h1 : null);
    $("anSummary").innerHTML = current.summary;
    $("anPx").textContent = fmt.price(m.price, m.symbol, m.digits);
    $("anBull").innerHTML = current.bull; $("anBear").innerHTML = current.bear;
    $("anTrend").innerHTML = current.trend; $("anVol").innerHTML = current.vol;
    $("anOpp").innerHTML = current.opportunity; $("anInv").innerHTML = current.invalidation;
    const { res, sup } = current.levels, P = v => fmt.price(v, m.symbol, m.digits);
    $("anLevels").innerHTML = res.length || sup.length ? `<div class="levels">${res.slice(0, 4).reverse().map(l => `<div class="lvl"><span class="down">RESIST</span><span>${P(l.price)}</span><span class="muted">${l.touches}× · ${((l.price - m.price) / m.price * 100).toFixed(2)}%</span></div>`).join("")}<div class="lvl now"><span>PRICE</span><span>${P(m.price)}</span><span></span></div>${sup.slice(0, 4).map(l => `<div class="lvl"><span class="up">SUPPORT</span><span>${P(l.price)}</span><span class="muted">${l.touches}× · ${((l.price - m.price) / m.price * 100).toFixed(2)}%</span></div>`).join("")}</div>` : empty(h1?.error || "No H1 swing levels found");
    const sigs = (store.data("signals")?.signals || []).filter(s => s.symbol === m.symbol).slice(0, 4);
    $("anSigs").innerHTML = sigs.length ? `<span class="kicker">Recent ${esc(m.symbol)} signals</span><table class="tbl"><tbody>${sigs.map(s => `<tr><td class="num muted">${fmt.dt(s.confirmed_at).slice(5)}</td><td>${dir(s.direction)}</td><td style="max-width:150px;overflow:hidden;text-overflow:ellipsis">${esc(s.strategy_name)}</td><td>${outcomeBadge(signalOutcome(s))}</td><td class="r ${tone(signalR(s))}">${fmt.r(signalR(s))}</td></tr>`).join("")}</tbody></table>` : "";
    $("anCites").innerHTML = `${icon("info")}<span>Sources: ${current.cites.map(esc).join(" · ")}. Scan ${ago(m.timestamp)}. This is market analysis, not personalised investment advice.</span>`;
    drawChat();
  }

  function drawIntel(m) {
    if (!m || !$("anIct") || !intel) return;
    const P = v => fmt.price(v, m.symbol, m.digits);
    if (!intel.ok) { ["anIct", "anConf", "anSetups"].forEach(id => { $(id).innerHTML = empty("Intelligence unavailable", esc(intel.error || "")); }); return; }
    ict = ictAnswers(intel, P);
    const x = intel.ict;
    $("anIct").innerHTML = `${structureHtml(x)}<div class="dsec" style="margin-top:14px"><h3>H1 dealing range</h3>${dealingHtml(x, P)}</div><div class="grid g-12 dsec"><div class="c-6"><h3 class="kicker">Liquidity map</h3>${ladderHtml(x, P)}</div><div class="c-6"><h3 class="kicker">FVGs & order blocks</h3>${zonesHtml(x, P)}</div></div><p class="source">${icon("info")}<span>Closed M15 bar ${fmt.dt(x.bar_closed_at)} UTC · ${esc(x.ny_time)} New York${x.kill_zone ? " · " + esc(x.kill_zone) : ""}. ${esc(x.basis)}</span></p>`;
    $("anConf").innerHTML = confluenceHtml(intel.confluence);
    $("anSetups").innerHTML = setupsHtml(x.setups, P) + `<p class="source">${icon("info")}<span>${esc(intel.mode)}. Stages: Watching → Developing → Confirming → Confirmed; only a closed-candle confirmation counts. ${esc(x.version)}.</span></p>`;
    drawChat();
  }

  function answer(q) {
    if (!current) return `Analysis for ${esc(symbol)} is unavailable until live data arrives.`;
    if (INTENTS.slice(0, 5).some(([re]) => re.test(q)) && !ict) return `The ICT intelligence layer for <b>${esc(symbol)}</b> is ${intel ? "unavailable (" + esc(intel.error || "") + ")" : "still loading"}, so I will not guess liquidity, structure or confluence.`;
    const hits = INTENTS.filter(([re]) => re.test(q)).map(([, f]) => f(current, ict)).filter(Boolean);
    if (hits.length) return [...new Set(hits)].slice(0, 2).join("<br><br>");
    return `I answer only from live engine data for <b>${esc(symbol)}</b>. Ask about the summary, liquidity levels, structure, confluence, what still needs to confirm, reversal risk, trend, key levels, scenarios, volatility or invalidation. To analyse another instrument, pick it from the watchlist.`;
  }
  function drawChat() {
    const log = $("anLog");
    if (!chatLog.length) log.innerHTML = `<div class="msg bot">Analysing <b>${esc(symbol)}</b>. ${current ? "Ask me anything about its structure, levels or setup." : "Waiting for live data…"}<span class="cite">Answers are composed from cited engine fields. If data is missing, I say so.</span></div>`;
    else log.innerHTML = chatLog.map(c => `<div class="msg ${c.who}">${c.html}${c.who === "bot" ? `<span class="cite">${esc(symbol)} · ${fmt.time(c.at)}</span>` : ""}</div>`).join("");
    log.scrollTop = log.scrollHeight;
  }
  function ask(q) {
    if (!q) return;
    chatLog.push({ who: "user", html: esc(q), at: Date.now() });
    chatLog.push({ who: "bot", html: answer(q), at: Date.now() });
    drawChat();
  }
  $("anForm").onsubmit = e => { e.preventDefault(); const v = $("anIn").value.trim(); $("anIn").value = ""; ask(v); };
  root.querySelectorAll("[data-ask]").forEach(b => b.onclick = () => ask(b.dataset.ask));
  $("anClear").onclick = () => { chatLog.length = 0; drawChat(); };

  drawSyms(); drawMain(true);
  return {
    keys: ["radar", "signals"],
    update(k) { if (k === "radar") { drawSyms(); if (!$("anChart")) drawMain(true); else fill(market()); } else fill(market()); },
    destroy() { token++; chart?.destroy(); },
  };
}
