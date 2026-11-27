import * as store from "../store.mjs";
import { esc, fmt, tone, icon, dir, lifecycle, badge, guard, empty, seg, sourceNote, stageBadge, stepper, sbadge, confPill, spark } from "../ui.mjs";
import { LIFECYCLE, lifecycleOf, biasOf, radarFilter, radarRank, atrPct, ago, breadth, trendStrength, assetClass, STAGE_INFO, isConfirmedStage, marketStatus } from "../model.mjs";
import { openMarket, volatilityFromCandles } from "./common.mjs";
import { SHORT } from "./intel.mjs";

export const subtitle = "Live opportunity scanner · lifecycle · confluence";
export const need = ["intel"];
const FILTERS = [["ALL", "All"], ["BULLISH", "Bullish"], ["BEARISH", "Bearish"], ["CONFLUENCE", "Confluence"]];
const SORTS = [["life", "Lifecycle"], ["conf", "Confluence"], ["move", "Move"], ["vol", "Volatility"]];
const PROD = { trendline_v5: "Trendline", support_resistance: "S/R levels", trend_momentum: "Trend momentum", smc: "SMC" };
const RANK = { NONE: 0, IDLE: 0, WATCHING: 1, DETECTED: 1, DEVELOPING: 2, CONFIRMING: 3, CONFIRMED: 4, ACTIVE: 5 };

// Stage of one production engine on a radar row (CONFIRMED only from the recorded lifecycle).
function engineStage(s) {
  const life = String(s.lifecycle_state || "").toUpperCase();
  if (s.confirmed === true && (life === "CONFIRMED" || life === "ACTIVE")) return life;
  return String(s.state || "NONE").toUpperCase();
}

export function mount(root, { params }) {
  let filter = params.filter || sessionStorage.getItem("td_rf") || "ALL";
  let view = localStorage.getItem("td_rview") || "grid", sort = localStorage.getItem("td_rsort") || "life", q = "";
  const sparks = {};
  root.innerHTML = `
    <div class="ph"><div><h1>Market Radar</h1><p>What the market is doing, which instruments have opportunities, which strategies see them, and how far each setup has progressed: <b style="color:var(--st-watching)">Watching</b> → <b style="color:var(--st-developing)">Developing</b> → <b style="color:var(--st-confirming)">Confirming</b> → <b style="color:var(--st-confirmed)">Confirmed</b> → <b style="color:var(--st-active)">Active</b>. Only Confirmed and Active are signals.</p></div>
      <div class="ph-a"><span id="rdScan"></span><a class="btn ghost" href="./classic.html" title="The original Garden radar, including setup history and archive">${icon("layers")}Garden view</a></div></div>
    <div class="pulse-band" id="rdPulse"></div>
    <div class="toolbar mt">
      <div class="field">${icon("search")}<input data-search id="rdQ" placeholder="Filter instruments or setups  /" autocomplete="off"></div>
      <div id="rdFilters"></div><span class="grow"></span>
      <span class="muted" style="font:500 10.5px var(--mono)">SORT</span>${seg("rdSort", SORTS, sort)}${seg("rdView", [["grid", "Cards"], ["table", "Table"]], view)}
    </div>
    <div class="mt" id="rdBody"></div>`;
  const $ = id => root.querySelector("#" + id);
  $("rdQ").oninput = e => { q = e.target.value.trim().toUpperCase(); drawBody(); };
  const segBind = (name, set) => root.querySelectorAll(`[data-seg="${name}"] button`).forEach(b => b.onclick = () => { set(b.dataset.v); root.querySelectorAll(`[data-seg="${name}"] button`).forEach(x => x.classList.toggle("on", x === b)); drawBody(); });
  segBind("rdView", v => { view = v; localStorage.setItem("td_rview", v); });
  segBind("rdSort", v => { sort = v; localStorage.setItem("td_rsort", v); });

  const markets = () => store.data("radar")?.markets || [];
  const intelOf = sym => (store.data("intel")?.markets || []).find(r => r.symbol === sym);
  const conf = m => intelOf(m.symbol)?.confluence;
  const pass = f => m => f === "CONFLUENCE" ? (conf(m)?.independent_families || 0) >= 2 && conf(m)?.classification !== "MIXED" : radarFilter(f)(m);
  function setFilter(f) { filter = f; sessionStorage.setItem("td_rf", f); drawFilters(); drawPulse(); drawBody(); }

  function drawFilters() {
    const ms = markets();
    $("rdFilters").innerHTML = `<div class="seg" data-seg="rdF">${FILTERS.map(([v, l]) => `<button data-v="${v}" class="${v === filter ? "on" : ""}">${l}<span class="n">${ms.filter(pass(v)).length}</span></button>`).join("")}</div>`;
    $("rdFilters").querySelectorAll("button").forEach(b => b.onclick = () => setFilter(b.dataset.v));
  }

  function drawPulse() {
    const ms = markets(), br = breadth(ms), ms0 = marketStatus();
    const intel = store.get("intel"), rows = intel.data?.markets || [];
    const pct = n => br.total ? (n / br.total * 100) : 0;
    const agree = rows.filter(r => (r.confluence?.independent_families || 0) >= 2 && r.confluence.classification !== "MIXED").length;
    const confirmedConf = rows.filter(r => r.confluence?.classification === "CONFIRMED CONFLUENCE").length;
    const ictDev = rows.reduce((n, r) => n + r.setups.filter(s => RANK[s.stage] >= 2).length, 0);
    const kz = rows[0];
    const vols = Object.values(sparks).map(s => s.vol?.percentile).filter(Number.isFinite);
    const avgVol = vols.length ? Math.round(vols.reduce((a, b) => a + b, 0) / vols.length) : null;
    const maxStage = Math.max(1, ...LIFECYCLE.map(s => br.stages[s]));
    $("rdPulse").innerHTML = `
      <section class="pulse-card"><h3>Market breadth <span>${br.total} instruments</span></h3>
        <div class="breadth-bar">${br.bullish ? `<i class="b-up" style="width:${pct(br.bullish)}%"></i>` : ""}${br.neutral ? `<i class="b-nt" style="width:${pct(br.neutral)}%"></i>` : ""}${br.bearish ? `<i class="b-dn" style="width:${pct(br.bearish)}%"></i>` : ""}</div>
        <div class="breadth-legend"><span><b class="up">${br.bullish}</b>Bullish</span><span style="text-align:center"><b>${br.neutral}</b>Range / neutral</span><span style="text-align:right"><b class="down">${br.bearish}</b>Bearish</span></div>
        <div class="pulse-meta" style="margin-top:12px"><div><span>Session</span><b>${esc(ms0.label)}</b></div><div><span>Avg. volatility percentile</span><b>${avgVol == null ? '<span class="na">loading</span>' : avgVol + "th"}</b></div></div></section>
      <section class="pulse-card"><h3>Signal lifecycle <span>only confirmed stages are signals</span></h3>
        <div class="funnel">${[["ALL", "Monitored", br.total], ...LIFECYCLE.map(s => [s, STAGE_INFO[s].label, br.stages[s]])].map(([v, l, n]) => `<button class="fstep ${filter === v ? "on" : ""}" data-v="${v}" title="${esc(v === "ALL" ? "All instruments" : STAGE_INFO[v].hint)}"><b>${n}</b><span>${l}</span><i style="transform:scaleX(${v === "ALL" ? 1 : n / maxStage})"></i></button>`).join("")}</div>
        <p class="source" style="margin-top:10px">${icon("info")}<span>${br.confirmed ? `<b class="up">${br.confirmed} confirmed</b> on the latest scan.` : "No confirmed setup on the latest scan."} Developing and confirming setups are hypotheses, not trade signals.</span></p></section>
      <section class="pulse-card"><h3>Intelligence <span class="ai">research layer</span></h3>
        ${intel.data ? `<div class="pulse-meta">
          <div><span>New York time · kill zone</span><b>${esc(kz?.ny_time || "—")} ${kz?.kill_zone ? `<span class="ai">${esc(kz.kill_zone)}</span>` : '<span class="muted">none</span>'}</b></div>
          <div><span>Independent confluence (≥2 families)</span><b class="${agree ? "info-t" : ""}">${agree}</b></div>
          <div><span>Confluence with a confirmed entry</span><b class="${confirmedConf ? "up" : ""}">${confirmedConf}</b></div>
          <div><span>ICT setups developing or later</span><b class="ai">${ictDev}</b></div></div>`
          : intel.status === "error" ? `<div class="empty unavailable" style="padding:4px 0">${icon("shield")}<div><b>Intelligence layer unavailable</b><p>${esc(intel.error)}. The running engine may predate this feature: restart it to load ICT context and confluence. Radar data below is unaffected.</p></div></div>` : `<div class="skel-wrap">${'<div class="skel" style="height:14px"></div>'.repeat(4)}</div>`}
      </section>`;
    $("rdPulse").querySelectorAll(".fstep").forEach(el => el.onclick = () => setFilter(el.dataset.v === filter ? "ALL" : el.dataset.v));
    const sc = store.data("radar")?.scan;
    $("rdScan").innerHTML = sc ? `<span class="chip" title="Scan interval ${sc.interval_seconds}s · stale after ${sc.stale_after_seconds}s"><span class="dot ${sc.status === "FRESH" ? "ok" : "warn"}"></span>Scan #${esc(sc.sequence)} · ${ago(sc.completed_at)} · ${Math.round((sc.elapsed_ms || 0) / 1000)}s</span>` : "";
  }

  function rows() {
    const byStage = LIFECYCLE.includes(filter);
    const list = markets().filter(m => byStage ? lifecycleOf(m) === filter : pass(filter)(m))
      .filter(m => !q || m.symbol.includes(q) || String(m.setup || "").toUpperCase().includes(q));
    const cmp = {
      life: radarRank,
      conf: (a, b) => (conf(b)?.net_agreement ?? conf(b)?.independent_families ?? 0) - (conf(a)?.net_agreement ?? conf(a)?.independent_families ?? 0) || radarRank(a, b),
      move: (a, b) => Math.abs(b.change_pct || 0) - Math.abs(a.change_pct || 0),
      vol: (a, b) => (sparks[b.symbol]?.vol?.percentile ?? -1) - (sparks[a.symbol]?.vol?.percentile ?? -1),
    }[sort] || radarRank;
    return list.sort(cmp);
  }

  function strategies(m) {
    const out = [];
    for (const s of m.strategies || []) {
      const st = engineStage(s);
      if (RANK[st] >= 2) out.push({ name: PROD[s.strategy_id] || s.strategy_id, stage: st, direction: s.direction, ict: false, rank: RANK[st] });
    }
    for (const s of intelOf(m.symbol)?.setups || []) {
      if (RANK[s.stage] >= 2) out.push({ name: SHORT[s.key] || s.name, stage: s.stage, direction: s.direction, ict: true, rank: RANK[s.stage], title: `${s.name} · ${s.stage}${s.missing?.length ? " · needs " + s.missing[0] : ""}` });
    }
    return out.sort((a, b) => b.rank - a.rank);
  }

  function gauges(m) {
    const ts = trendStrength(m), sp = sparks[m.symbol], v = sp?.vol;
    const tsW = ts == null ? 0 : Math.abs(ts) * 50;
    const tsLbl = ts == null ? "—" : Math.abs(ts) < 0.2 ? "Flat" : (Math.abs(ts) > 0.66 ? "Strong " : "") + (ts > 0 ? "up" : "down");
    const lvl = v?.percentile == null ? -1 : Math.min(4, Math.floor(v.percentile / 20));
    const vc = lvl >= 4 ? "var(--down)" : lvl === 3 ? "var(--amber)" : lvl >= 1 ? "var(--teal)" : "var(--accent)";
    const rsi = Number(m.rsi);
    return `<div class="rc-gauges">
      <div class="gauge" title="EMA20-EMA50 spread in ATR (M15); HTF bias ${esc(m.higher_timeframe_bias || "—")}"><span>Trend<em class="${ts > 0.2 ? "up" : ts < -0.2 ? "down" : ""}">${tsLbl}</em></span><div class="bar center"><i style="${ts >= 0 ? "left:50%" : `left:${50 - tsW}%`};width:${tsW}%;background:${ts >= 0 ? "var(--up)" : "var(--down)"}"></i></div></div>
      <div class="gauge" title="${v ? `M15 ATR(14) at the ${v.percentile}th percentile of the last ${sp.n} bars · ${(atrPct(m) ?? 0).toFixed(2)}% of price` : "Volatility history loading"}"><span>Volatility<em>${v?.percentile == null ? "—" : esc(v.regime.toLowerCase())}</em></span><div class="segs" style="--vc:${vc}">${[0, 1, 2, 3, 4].map(k => `<i class="${k <= lvl ? "on" : ""}"></i>`).join("")}</div></div>
      <div class="gauge" title="RSI(14) on M15 · band 30-70"><span>RSI<em class="${rsi >= 70 ? "down" : rsi <= 30 ? "up" : ""}">${fmt.num(rsi, 0)}</em></span><div class="bar"><span class="rsi-band"></span>${Number.isFinite(rsi) ? `<span class="rsi-mark" style="left:${Math.max(0, Math.min(100, rsi))}%"></span>` : ""}</div></div>
    </div>`;
  }

  function status(m, st) {
    const P = v => fmt.price(v, m.symbol, m.digits);
    if (isConfirmedStage(st)) return `<div class="rc-status ok">${icon("bolt")}<p><b>Confirmed ${m.direction === "LONG" ? "buy" : "sell"} · ${esc(m.setup || "")}</b>${Number.isFinite(m.entry) ? ` · entry ${P(m.entry)} · SL ${P(m.stop_loss)} · TP ${P(m.take_profit)}` : ""}</p></div>`;
    const ictNeed = (intelOf(m.symbol)?.setups || []).filter(s => RANK[s.stage] >= 2).sort((a, b) => RANK[b.stage] - RANK[a.stage])[0];
    if (st === "CONFIRMING") return `<div class="rc-status">${icon("info")}<p><b>Not a signal yet.</b> Awaiting ${esc(m.trigger || "confirmation")}.</p></div>`;
    if (st === "DEVELOPING") return `<div class="rc-status">${icon("info")}<p><b>Developing · ${esc(m.setup || "")}.</b> Needs ${esc(m.trigger || "confirmation")}.</p></div>`;
    if (ictNeed) return `<div class="rc-status">${icon("analyst")}<p><b>ICT ${esc(SHORT[ictNeed.key] || ictNeed.name)} ${esc(ictNeed.stage.toLowerCase())}.</b> ${ictNeed.missing?.length ? "Needs " + esc(ictNeed.missing[0]) + "." : ""}</p></div>`;
    return `<div class="rc-status">${icon("radar")}<p><b>Watching.</b> ${esc(m.setup || "Context only")}: no setup is forming.</p></div>`;
  }

  function card(m) {
    const st = lifecycleOf(m), b = biasOf(m), sp = sparks[m.symbol];
    const strats = strategies(m);
    const c = conf(m);
    return `<article class="rcard" data-stage="${st}" data-bias="${b}" data-sym="${esc(m.symbol)}" tabindex="0" role="button" aria-label="${esc(m.symbol)} ${st}">
      <div class="rc-top"><div class="rc-id"><span class="sym">${esc(m.symbol)}</span><span class="cls">${assetClass(m.symbol)}</span>
          <div class="rc-tags">${badge(b === "BULLISH" ? "Bullish" : b === "BEARISH" ? "Bearish" : "Neutral", b === "BULLISH" ? "good" : b === "BEARISH" ? "bad" : "muted")}${stageBadge(st)}${m.direction && st !== "WATCHING" && st !== "IDLE" ? dir(m.direction) : ""}</div></div>
        <div class="rc-px"><b data-num="${m.price}" data-key="rp-${esc(m.symbol)}">${fmt.price(m.price, m.symbol, m.digits)}</b><span class="${tone(m.change_pct)}">${fmt.pct(m.change_pct)}</span></div></div>
      <div class="rc-spark">${sp?.closes?.length > 2 ? spark(sp.closes, { w: 300, h: 46 }) : `<div class="na-spark">${sp?.error ? esc(sp.error) : "Loading M15 candles…"}</div>`}</div>
      ${gauges(m)}
      <div class="rc-strats">${strats.length ? strats.slice(0, 4).map(s => sbadge(s)).join("") + (strats.length > 4 ? `<span class="sbadge">+${strats.length - 4}</span>` : "") : '<span class="muted" style="font-size:11px">No strategy is developing a setup</span>'}</div>
      <div class="rc-life">${stepper(st === "IDLE" ? "WATCHING" : st)}</div>
      ${status(m, st)}
      <div class="rc-foot">${c ? confPill(c) : "<span></span>"}<time title="${esc(m.timestamp)}">${esc(m.session || "")} · ${ago(m.timestamp)}</time></div>
    </article>`;
  }

  function drawBody() {
    const e = store.get("radar");
    $("rdBody").innerHTML = guard(e, () => {
      const list = rows();
      if (!list.length) return `<section class="panel">${empty("No instruments match this filter", filter === "ALL" ? "Try clearing the search." : "Nothing is currently in this group.")}</section>`;
      if (view === "table") return `<section class="panel flush"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Instrument</th><th class="r">Price</th><th class="r">Change</th><th>Bias</th><th>Trend</th><th class="r">Vol. pct</th><th class="r">RSI</th><th>Setup</th><th>Strategies</th><th>Lifecycle</th><th>Confluence</th><th class="r">Updated</th></tr></thead><tbody>
        ${list.map(m => { const b = biasOf(m), ts = trendStrength(m), st = lifecycleOf(m), s = strategies(m); return `<tr class="click" data-sym="${esc(m.symbol)}"><td><span class="sym">${esc(m.symbol)}</span></td><td class="r">${fmt.price(m.price, m.symbol, m.digits)}</td><td class="r ${tone(m.change_pct)}">${fmt.pct(m.change_pct)}</td><td><span class="${b === "BULLISH" ? "up" : b === "BEARISH" ? "down" : "muted"}">${b}</span> <span class="muted">· HTF ${esc(m.higher_timeframe_bias || "—")}</span></td><td class="r ${tone(ts)}">${ts == null ? "—" : (ts > 0 ? "+" : "") + ts.toFixed(2)}</td><td class="r">${sparks[m.symbol]?.vol?.percentile ?? "—"}</td><td class="r">${fmt.num(m.rsi, 0)}</td><td>${st !== "WATCHING" ? dir(m.direction) : ""} <span class="muted">${esc(m.setup || "")}</span></td><td>${s.slice(0, 3).map(x => sbadge(x)).join(" ") || '<span class="na">—</span>'}</td><td>${lifecycle(st)}</td><td>${confPill(conf(m)) || '<span class="na">—</span>'}</td><td class="r muted">${ago(m.timestamp)}</td></tr>`; }).join("")}
      </tbody></table></div></section>`;
      return `<div class="radar-grid">${list.map(card).join("")}</div>`;
    }, "Market Radar") + sourceNote("Live MT5 data via the autonomous scanner. Trend = EMA20–EMA50 spread in M15 ATR; volatility = M15 ATR(14) percentile over the last 200 bars; lifecycle stages are the recorded episode lifecycle (Confirmed/Active) or the scanner's own state. Strategy chips show engines and ICT research setups at Developing or later; ICT setups run in shadow and are never alerted. Confluence counts independent evidence families, not strategies.");
    $("rdBody").querySelectorAll("[data-sym]").forEach(el => {
      const open = () => openMarket(markets().find(m => m.symbol === el.dataset.sym));
      el.onclick = open; el.onkeydown = ev => { if (ev.key === "Enter") open(); };
    });
  }

  let loading = false;
  async function loadSparks() {
    if (loading) return; loading = true;
    const ms = markets();
    await Promise.all(ms.map(async m => {
      const res = await store.candles(m.symbol, "M15", 200, { maxAge: 120000 });
      if (!res.ok || !res.candles.length) { sparks[m.symbol] = { error: res.error || "No candles" }; return; }
      sparks[m.symbol] = { closes: res.candles.slice(-96).map(c => c.close), vol: volatilityFromCandles(res.candles), n: res.candles.length };
    }));
    loading = false;
    if (root.isConnected) { drawPulse(); drawBody(); }
  }

  drawFilters(); drawPulse(); drawBody(); loadSparks();
  const timer = setInterval(loadSparks, 120000);
  return {
    keys: ["radar", "intel"],
    update(k) { drawFilters(); drawPulse(); drawBody(); if (k === "radar" && !Object.keys(sparks).length) loadSparks(); },
    destroy() { clearInterval(timer); },
  };
}
