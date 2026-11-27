import "./app.css";
import * as store from "./store.mjs";
import { esc, icon, logo, fmt, tone, toast, onNotify, getNotifications, markRead, animateNumbers, closeDrawer } from "./ui.mjs";
import { marketStatus, FEATURED, ago } from "./model.mjs";
import { initIdentity, identityState, authRequired, signIn } from "../userJournal.mjs";
import { initTheme, toggle as toggleTheme, current as currentTheme } from "./theme.mjs";

const PAGES = [
  { id: "overview", label: "Overview", icon: "overview", load: () => import("./pages/overview.mjs") },
  { id: "radar", label: "Market Radar", icon: "radar", load: () => import("./pages/radar.mjs") },
  { id: "analyst", label: "AI Analyst", icon: "analyst", load: () => import("./pages/analyst.mjs") },
  { id: "signals", label: "Signal Centre", icon: "signals", load: () => import("./pages/signals.mjs") },
  { id: "lab", label: "Strategy Lab", icon: "lab", load: () => import("./pages/lab.mjs") },
  { id: "participation", label: "Strategy Participation", icon: "grid", load: () => import("./pages/participation.mjs") },
  { id: "portfolio", label: "Portfolio", icon: "portfolio", load: () => import("./pages/portfolio.mjs") },
  { id: "analytics", label: "Analytics", icon: "analytics", load: () => import("./pages/analytics.mjs") },
  { id: "history", label: "Trade History", icon: "history", load: () => import("./pages/history.mjs") },
  { id: "settings", label: "Settings", icon: "settings", load: () => import("./pages/settings.mjs") },
];
const byId = Object.fromEntries(PAGES.map(p => [p.id, p]));
const pref = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const setPref = (k, v) => { try { localStorage.setItem(k, v); } catch {} };

let current = null, currentId = null, navToken = 0;
const root = document.getElementById("root");
document.documentElement.dataset.motion = pref("td_motion", "on");
initTheme();

function shell() {
  root.innerHTML = `
  <div class="td ${pref("td_sidebar", "open") === "collapsed" ? "collapsed" : ""}" id="td">
    <div class="scrim" id="scrim"></div>
    <aside class="sb" aria-label="Primary">
      <div class="sb-brand">${logo()}<div class="wordmark">TRADEDEN<small>INTELLIGENCE TERMINAL</small></div></div>
      <nav class="sb-nav">
        <div class="sb-sec">Markets</div>
        ${PAGES.slice(0, 4).map(navItem).join("")}
        <div class="sb-sec">Research</div>
        ${PAGES.slice(4, 6).map(navItem).join("")}
        <div class="sb-sec">Performance</div>
        ${PAGES.slice(6, 9).map(navItem).join("")}
      </nav>
      <div class="sb-foot">
        <div class="sb-safe">${icon("shield")}<div><b>Execution locked</b>Signals only. The engine places no orders.</div></div>
        ${navItem(PAGES[9])}
        <button class="nav collapse-btn" id="collapse" data-tip="Collapse sidebar  [">${icon("collapse")}<span>Collapse</span></button>
      </div>
    </aside>
    <div class="main">
      <header class="hdr">
        <button class="icon-btn menu-btn" id="menuBtn" aria-label="Open navigation">${icon("menu")}</button>
        <div class="hdr-title"><b id="pgTitle"></b><small id="pgSub"></small></div>
        <div class="hdr-mid" id="hdrStatus"></div>
        <div class="hdr-r">
          <div class="clock" id="clock"></div>
          <button class="icon-btn theme-btn" id="themeBtn" aria-label="Switch theme" title="Switch theme  [t]"></button>
          <div class="rel"><button class="icon-btn" id="bellBtn" aria-label="Notifications" aria-haspopup="true">${icon("bell")}<span class="pip" id="bellPip" hidden></span></button><div class="dropdown" id="bellDd"></div></div>
          <div class="rel"><button class="avatar" id="userBtn" aria-label="Workspace">TD</button><div class="dropdown" id="userDd" style="width:260px"></div></div>
        </div>
      </header>
      <div class="ticker" id="ticker" aria-label="Monitored instruments"><span class="tick-msg">Connecting to market engine…</span></div>
      <main id="page"></main>
    </div>
  </div>`;
  bindShell();
}
const navItem = (p, i) => `<button class="nav" data-nav="${p.id}" data-tip="${esc(p.label)}">${icon(p.icon)}<span>${p.label}</span>${p.id === "signals" ? `<em class="count" id="sigCount" hidden></em>` : ""}<kbd>${(PAGES.indexOf(p) + 1) % 10}</kbd></button>`;

function bindShell() {
  const td = document.getElementById("td");
  root.querySelectorAll("[data-nav]").forEach(b => b.onclick = () => { go(b.dataset.nav); td.classList.remove("mnav"); });
  document.getElementById("collapse").onclick = toggleSidebar;
  document.getElementById("themeBtn").onclick = toggleTheme;
  renderThemeBtn();
  document.getElementById("menuBtn").onclick = () => td.classList.toggle("mnav");
  document.getElementById("scrim").onclick = () => td.classList.remove("mnav");
  const dd = (btn, box, fill) => {
    document.getElementById(btn).onclick = e => {
      e.stopPropagation();
      const el = document.getElementById(box), open = !el.classList.contains("open");
      document.querySelectorAll(".dropdown.open").forEach(x => x.classList.remove("open"));
      if (open) { fill(el); el.classList.add("open"); }
    };
  };
  dd("bellBtn", "bellDd", fillBell);
  dd("userBtn", "userDd", fillUser);
  document.addEventListener("click", e => { if (!e.target.closest(".dropdown")) document.querySelectorAll(".dropdown.open").forEach(x => x.classList.remove("open")); });
  // Tooltips for collapsed sidebar
  let tip = null;
  root.querySelectorAll("[data-tip]").forEach(el => {
    el.addEventListener("mouseenter", () => {
      if (!td.classList.contains("collapsed") || innerWidth <= 860) return;
      tip = document.createElement("div"); tip.className = "tip"; tip.textContent = el.dataset.tip; document.body.appendChild(tip);
      const r = el.getBoundingClientRect(); tip.style.left = r.right + 10 + "px"; tip.style.top = r.top + r.height / 2 - tip.offsetHeight / 2 + "px";
    });
    el.addEventListener("mouseleave", () => { tip?.remove(); tip = null; });
  });
  onNotify(updateBell);
}
function renderThemeBtn() {
  const b = document.getElementById("themeBtn"); if (!b) return;
  const light = currentTheme() === "light";
  b.innerHTML = icon(light ? "moon" : "sun");
  b.setAttribute("aria-label", light ? "Switch to dark mode" : "Switch to light mode");
  b.title = (light ? "Dark mode" : "Light mode") + "  [t]";
  b.setAttribute("aria-pressed", String(light));
}
// A theme change repaints CSS instantly; canvas charts read colours once, so the current page is
// re-mounted in place (same route, same scroll position) to redraw them in the new palette.
window.addEventListener("td:theme", () => {
  renderThemeBtn();
  if (!currentId || !current) return;
  const y = window.scrollY;
  route({ keepScroll: true }).then(() => window.scrollTo({ top: y }));
});
function toggleSidebar() {
  const td = document.getElementById("td");
  td.classList.toggle("collapsed");
  setPref("td_sidebar", td.classList.contains("collapsed") ? "collapsed" : "open");
}

function fillBell(el) {
  const { list } = getNotifications();
  el.innerHTML = `<header>Notifications <button class="btn sm ghost" id="clearN">Mark read</button></header>` + (list.length
    ? list.map(n => `<div class="dd-item ${n.kind}"><i></i><div><b>${esc(n.title)}</b>${n.body ? `<p>${esc(n.body)}</p>` : ""}</div><time>${ago(n.at)}</time></div>`).join("")
    : `<div class="empty">${icon("bell")}<div><b>No notifications yet</b><p>New confirmed signals, lifecycle changes and connection events appear here.</p></div></div>`);
  markRead();
  el.querySelector("#clearN").onclick = () => { markRead(); el.classList.remove("open"); };
}
function updateBell() { const pip = document.getElementById("bellPip"); if (pip) pip.hidden = !getNotifications().unread; }
function fillUser(el) {
  const u = identityState.user;
  el.innerHTML = `<header>${u ? esc(u.email || u.name || "Account") : "Private workspace"}</header>
   <div class="dd-item"><i></i><div><b>${esc(identityState.entitlements?.plan || "Owner")} plan</b><p>${u ? "Signed in · cloud journal active" : "Local workspace · journal stored in this browser"}</p></div><span></span></div>
   <div class="dd-item"><i></i><div><b>Engine</b><p class="mono">${esc(store.get("health").data?.service || "—")} ${esc(store.get("health").data?.engine_version || "")}</p></div><span></span></div>
   <div style="padding:10px 12px;display:flex;gap:6px;flex-wrap:wrap"><button class="btn sm" data-goto="settings">${icon("settings")}Settings</button><a class="btn sm ghost" href="./classic.html">${icon("layers")}Classic Garden</a></div>`;
  el.querySelector("[data-goto]").onclick = () => { el.classList.remove("open"); go("settings"); };
}

// Header status: session, market status, engine/MT5/cTrader connections.
function renderStatus() {
  const box = document.getElementById("hdrStatus"); if (!box) return;
  const ms = marketStatus();
  const h = store.get("health"), sc = store.get("scalper");
  const hd = h.data;
  const engine = h.status === "ok" ? ["ok", "Online"] : h.status === "error" ? ["bad", "Offline"] : ["warn", "Connecting"];
  const mt5 = !hd || h.status === "error" ? ["off", "Unknown"] : hd.mt5_connected ? ["ok", "Connected"] : ["bad", hd.mt5_status || "Offline"];
  const fresh = hd?.data_freshness?.status;
  const age = sc.data?.heartbeat_age_seconds;
  const ct = sc.status === "error" || !sc.data ? ["off", "Unavailable"] : Number.isFinite(age) && age < 180 ? ["ok", "Connected"] : ["warn", sc.data.bot_status === "stopped" ? "Bot stopped" : "No heartbeat"];
  const ctTitle = sc.data ? `cTrader ${sc.data.account?.verification || ""} · last heartbeat ${Number.isFinite(age) ? fmtAge(age) + " ago" : "never"}` : "cTrader journal endpoint unavailable";
  box.innerHTML = `
    <span class="chip opt" title="Active trading sessions (UTC)"><span class="dot ${ms.fxOpen ? "ok" : "off"}"></span><b>${esc(ms.label)}</b></span>
    <span class="chip opt" title="Scanner data freshness">${fresh === "FRESH" ? '<span class="dot ok"></span>Feed fresh' : fresh === "STALE" ? '<span class="dot warn"></span>Feed stale' : '<span class="dot off"></span>Feed —'}</span>
    <span class="chip" title="Market engine API ${esc(h.error || "")}"><span class="dot ${engine[0]}"></span>API <b>${engine[1]}</b></span>
    <span class="chip" title="MetaTrader 5 terminal"><span class="dot ${mt5[0]}"></span>MT5 <b>${mt5[1]}</b></span>
    <span class="chip" title="${esc(ctTitle)}"><span class="dot ${ct[0]}"></span>cTrader <b>${ct[1]}</b></span>`;
}
const fmtAge = s => s < 90 ? Math.round(s) + "s" : s < 5400 ? Math.round(s / 60) + "m" : s < 172800 ? Math.round(s / 3600) + "h" : Math.round(s / 86400) + "d";

function renderClock() {
  const el = document.getElementById("clock"); if (!el) return;
  const d = new Date();
  el.innerHTML = `${d.toISOString().slice(11, 19)} UTC<small>${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} local</small>`;
}

// Ticker of monitored instruments (live radar prices only).
let tickerSig = "";
function renderTicker() {
  const el = document.getElementById("ticker"); if (!el) return;
  const r = store.get("radar");
  if (!r.data?.markets?.length) {
    el.innerHTML = `<span class="tick-msg">${r.status === "error" ? "Market engine unreachable · no prices shown" : "Connecting to market engine…"}</span>`; tickerSig = ""; return;
  }
  const mk = [...r.data.markets].sort((a, b) => (FEATURED.indexOf(a.symbol) + 99) % 99 - (FEATURED.indexOf(b.symbol) + 99) % 99);
  const items = mk.map(m => `<span class="tick-item" data-sym="${esc(m.symbol)}"><b>${esc(m.symbol)}</b><span>${fmt.price(m.price, m.symbol, m.digits)}</span><span class="${tone(m.change_pct)}">${fmt.pct(m.change_pct)}</span></span>`).join("");
  const sig = mk.map(m => m.symbol + m.price).join();
  if (sig === tickerSig) return; tickerSig = sig;
  const track = el.querySelector(".tick-track");
  if (track) { track.innerHTML = items + items; }
  else { el.innerHTML = `<div class="tick-track">${items}${items}</div>`; }
  el.querySelector(".tick-track").onclick = e => { const s = e.target.closest("[data-sym]"); if (s) go("analyst", { symbol: s.dataset.sym }); };
}

// Live notifications: new bank signals and radar lifecycle progressions.
let seenSignals = null, lastStages = null, lastEngine = null;
function watchEvents(key, entry) {
  if (key === "signals" && entry.data?.signals) {
    const ids = new Set(entry.data.signals.map(s => s.signal_id));
    if (seenSignals) for (const s of entry.data.signals) if (!seenSignals.has(s.signal_id) && Date.now() - Date.parse(s.confirmed_at) < 3600e3)
      toast(`New signal · ${s.symbol} ${s.direction === "LONG" ? "BUY" : "SELL"}`, { body: `${s.strategy_name} · entry ${s.entry} · SL ${s.stop_loss} · TP ${s.take_profit}`, kind: "good" });
    seenSignals = ids;
    const open = entry.data.signals.filter(s => s.outcome_status === "PENDING").length;
    const c = document.getElementById("sigCount"); if (c) { c.hidden = !open; c.textContent = open; }
  }
  if (key === "radar" && entry.data?.markets) {
    const now = Object.fromEntries(entry.data.markets.map(m => [m.symbol, String(m.lifecycle_state || m.state)]));
    if (lastStages) for (const [sym, st] of Object.entries(now)) {
      const prev = lastStages[sym];
      if (prev && prev !== st && /CONFIRM|ACTIVE/.test(st)) toast(`${sym} → ${st}`, { body: "Market Radar lifecycle progressed", kind: "warn" });
    }
    lastStages = now;
  }
  if (key === "health" && (entry.status === "ok" || entry.status === "error")) {
    const ok = entry.status === "ok";
    if (lastEngine !== null && ok !== lastEngine) toast(ok ? "Engine reconnected" : "Engine connection lost", { body: ok ? "Live data resumed." : entry.error || "", kind: ok ? "good" : "bad" });
    lastEngine = ok;
  }
}

// Routing
function parseHash() {
  const [id, q] = location.hash.replace(/^#\/?/, "").split("?");
  return { id: byId[id] ? id : "overview", params: Object.fromEntries(new URLSearchParams(q || "")) };
}
export function go(id, params = {}) {
  const q = new URLSearchParams(params).toString();
  const hash = "#/" + id + (q ? "?" + q : "");
  if (location.hash === hash) route(); else location.hash = hash;
}
window.tdGo = go;

async function route({ keepScroll = false } = {}) {
  const { id, params } = parseHash();
  const token = ++navToken;
  closeDrawer();
  document.getElementById("td")?.classList.remove("mnav");
  document.querySelectorAll(".dropdown.open").forEach(x => x.classList.remove("open"));
  if (current?.destroy) { try { current.destroy(); } catch (e) { console.error(e); } }
  current = null;
  root.querySelectorAll("[data-nav]").forEach(b => { b.classList.toggle("on", b.dataset.nav === id); b.setAttribute("aria-current", b.dataset.nav === id ? "page" : "false"); });
  const meta = byId[id];
  const pageEl = document.getElementById("page");
  if (!keepScroll) pageEl.innerHTML = `<div class="page"><div class="skel-wrap">${'<div class="skel" style="height:72px"></div>'.repeat(3)}</div></div>`;
  let mod;
  try { mod = await meta.load(); } catch (e) { console.error(e); pageEl.innerHTML = `<div class="page">${icon("info")} This page failed to load. Reload to retry.</div>`; return; }
  if (token !== navToken) return;
  currentId = id;
  document.getElementById("pgTitle").textContent = meta.label;
  document.getElementById("pgSub").textContent = mod.subtitle || "";
  document.title = meta.label + " · TRADEDEN";
  store.need(mod.need || []);
  pageEl.innerHTML = "";
  const host = document.createElement("div"); host.className = "page"; host.dataset.sec = id; pageEl.appendChild(host);
  current = mod.mount(host, { params, go, store }) || {};
  if (!keepScroll) { animateNumbers(host); window.scrollTo({ top: 0 }); } else host.style.animation = "none";
}

store.subscribe((key, entry) => {
  watchEvents(key, entry);
  if (key === "health" || key === "scalper") renderStatus();
  if (key === "radar") renderTicker();
  if (current?.update && (current.keys || []).includes(key)) {
    try { current.update(key); } catch (e) { console.error(e); }
    animateNumbers(document.getElementById("page"));
  }
});

// Keyboard shortcuts
document.addEventListener("keydown", e => {
  if (e.target.closest("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) {
    if (e.key === "Escape") e.target.blur?.();
    return;
  }
  if (e.key === "Escape") { if (!closeDrawer()) document.querySelectorAll(".dropdown.open").forEach(x => x.classList.remove("open")); return; }
  const n = e.key === "0" ? 10 : Number(e.key);
  if (n >= 1 && n <= PAGES.length) { go(PAGES[n - 1].id); e.preventDefault(); return; }
  if (e.key === "[") { toggleSidebar(); return; }
  if (e.key === "/") { const s = document.querySelector("[data-search]"); if (s) { s.focus(); e.preventDefault(); } return; }
  if (e.key === "r") { store.refreshAll(); toast("Refreshing engine data", { record: false, ms: 1500 }); }
  if (e.key === "t") { toggleTheme(); }
});

function start() {
  shell();
  renderClock(); setInterval(renderClock, 1000); setInterval(renderStatus, 30000);
  renderStatus();
  window.addEventListener("hashchange", () => route());
  route();
}

// Hosted builds that require accounts show a sign-in gate first; the local
// owner workspace starts immediately (it has no session endpoint to ask).
if (authRequired()) {
  root.innerHTML = `<div style="min-height:100vh;display:grid;place-items:center;padding:16px"><div class="panel" style="max-width:380px;width:100%;padding:28px;text-align:center">${logo()}<h1 style="font-size:18px;margin:14px 0 6px">TRADEDEN</h1><p class="dsub">Sign in to your trading intelligence workspace.</p><button class="btn primary" id="signInBtn" style="margin-top:8px">Sign in securely</button></div></div>`;
  initIdentity().then(() => identityState.user ? start() : (document.getElementById("signInBtn").onclick = signIn))
    .catch(() => { root.querySelector(".dsub").textContent = "Account service unavailable. Reload to retry."; });
} else {
  start();
  if (location.protocol === "https:") initIdentity().catch(() => {});
}
