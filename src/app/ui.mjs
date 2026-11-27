// TRADEDEN UI kit: formatting, icons and small HTML components.
import { priceDigits, LIFECYCLE, ago } from "./model.mjs";

export const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const NA = '<span class="na">—</span>';
const fin = v => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));

export const fmt = {
  price: (v, sym, digits) => fin(v) ? Number(v).toLocaleString("en-US", { minimumFractionDigits: priceDigits(sym, v, digits), maximumFractionDigits: priceDigits(sym, v, digits) }) : "—",
  pct: (v, d = 2, signed = true) => fin(v) ? (signed && v > 0 ? "+" : "") + Number(v).toFixed(d) + "%" : "—",
  ratio: (v, d = 1) => fin(v) ? (Number(v) * 100).toFixed(d) + "%" : "—",
  r: (v, d = 2) => fin(v) ? (v > 0 ? "+" : "") + Number(v).toFixed(d) + "R" : "—",
  num: (v, d = 2) => fin(v) ? Number(v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }) : "—",
  int: v => fin(v) ? Math.round(Number(v)).toLocaleString("en-US") : "—",
  money: (v, cur = "USD", signed = false) => fin(v) ? (signed && v > 0 ? "+" : v < 0 ? "−" : "") + new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD", maximumFractionDigits: 2 }).format(Math.abs(v)) : "—",
  time: v => { const t = typeof v === "number" ? v : Date.parse(v); return Number.isFinite(t) ? new Date(t).toISOString().slice(11, 16) + " UTC" : "—"; },
  dt: v => { const t = typeof v === "number" ? v : Date.parse(v); return Number.isFinite(t) ? new Date(t).toISOString().slice(0, 16).replace("T", " ") : "—"; },
  date: v => { const t = typeof v === "number" ? v : Date.parse(v); return Number.isFinite(t) ? new Date(t).toISOString().slice(0, 10) : "—"; },
  ago,
};
export const tone = v => !fin(v) ? "" : Number(v) > 0 ? "up" : Number(v) < 0 ? "down" : "";

// Icons: 24px stroke paths, drawn in currentColor.
const P = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/><circle cx="12" cy="12" r="1"/>',
  analyst: '<path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  signals: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  lab: '<path d="M9 3h6"/><path d="M10 3v6l-5.5 9.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3"/><path d="M7.5 15h9"/>',
  portfolio: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M3 13h18"/>',
  analytics: '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 6-7"/>',
  history: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  collapse: '<path d="M15 6l-6 6 6 6"/><path d="M20 4v16"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  up: '<path d="M7 17L17 7"/><path d="M8 7h9v9"/>',
  down: '<path d="M7 7l10 10"/><path d="M17 8v9H8"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.9-3.9L4 9"/><path d="M4 4v5h5"/><path d="M4 13a8 8 0 0 0 14.9 3.9L20 15"/><path d="M20 20v-5h-5"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  upload: '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 20h16"/>',
  send: '<path d="M4 12l16-8-6 16-2-7z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20.5 14.2A8.5 8.5 0 1 1 9.8 3.5a7 7 0 0 0 10.7 10.7z"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
};
export const icon = (name, cls = "") => `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ""}</svg>`;

export const logo = () => `<svg class="logo" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2fd59a"/><stop offset=".55" stop-color="#4f9dff"/><stop offset="1" stop-color="#a98bff"/></linearGradient></defs><rect x="1" y="1" width="30" height="30" rx="8" fill="#0d1630" stroke="url(#lg)" stroke-opacity=".6"/><path d="M8 21l5-6 4 3 7-9" fill="none" stroke="url(#lg)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><circle cx="24" cy="9" r="2" fill="#a98bff"/></svg>`;

// Components
export function panel({ title, kicker = "", actions = "", body = "", cls = "", id = "" }) {
  return `<section class="panel ${cls}"${id ? ` id="${id}"` : ""}><header class="panel-h"><div>${kicker ? `<span class="kicker">${kicker}</span>` : ""}<h2>${title}</h2></div><div class="panel-a">${actions}</div></header><div class="panel-b">${body}</div></section>`;
}
export function stat({ label, value, sub = "", cls = "", key = "", num = null, title = "" }) {
  const n = num != null && Number.isFinite(num) ? ` data-num="${num}" data-key="${esc(key || label)}"` : "";
  return `<div class="stat ${cls}"${title ? ` title="${esc(title)}"` : ""}><span class="stat-l">${label}</span><strong class="stat-v"${n}>${value}</strong>${sub ? `<small class="stat-s">${sub}</small>` : ""}</div>`;
}
export const dir = d => {
  const long = /LONG|BUY/i.test(d || "");
  if (!d) return NA;
  return `<span class="dir ${long ? "long" : "short"}">${icon(long ? "up" : "down")}${long ? "BUY" : "SELL"}</span>`;
};
export const badge = (text, kind = "") => `<span class="badge ${kind}">${esc(text)}</span>`;
const STAGES = ["WATCHING", "DEVELOPING", "CONFIRMING", "CONFIRMED", "ACTIVE"];
export const stageBadge = s => badge(s, STAGES.includes(s) ? "st-" + s.toLowerCase() : "muted");
export const outcomeBadge = o => badge(o, o === "WIN" ? "good" : o === "LOSS" ? "bad" : o === "OPEN" ? "live" : "muted");
export const tierBadge = t => badge(t, ["PRODUCTION", "VALIDATED", "RESEARCH", "EXPERIMENTAL", "SUSPENDED"].includes(t) ? "tier-" + t.toLowerCase() : "muted");

// Labelled lifecycle stepper WATCHING -> ACTIVE. Stages after the current one stay dark.
export function stepper(stage) {
  const idx = STAGES.indexOf(stage);
  return `<div class="stepper" title="Lifecycle: ${esc(stage)}">${STAGES.map((s, i) => `<span class="st ${i < idx ? "done" : i === idx ? "on" + (s === "CONFIRMING" ? " pulse" : "") : ""}" data-s="${s}">${s === "CONFIRMING" ? "Confirm." : s[0] + s.slice(1).toLowerCase()}</span>`).join("")}</div>`;
}
// Strategy identification chip: stage dot, short name, direction.
export function sbadge({ name, stage, direction, ict = false, title = "" }) {
  const d = /LONG|BUY|BULL/i.test(direction || "") ? "long" : /SHORT|SELL|BEAR/i.test(direction || "") ? "short" : "";
  return `<span class="sbadge ${ict ? "ict" : ""}" data-s="${esc(stage)}" title="${esc(title || name + " · " + stage)}"><i></i>${ict ? "<b>ICT</b>" : ""}${esc(name)}${d ? `<span class="d ${d}">${d === "long" ? "▲" : "▼"}</span>` : ""}</span>`;
}
// Confluence pill: independent families agreeing (never a strategy count).
export function confPill(c) {
  if (!c) return "";
  const n = c.independent_families || 0;
  const cls = c.classification === "CONFIRMED CONFLUENCE" ? "confirmed" : c.classification === "DIRECTIONAL AGREEMENT" ? "agree" : c.classification === "MIXED" ? "mixed" : "";
  const label = c.classification === "NONE" ? "No confluence" : c.classification === "MIXED" ? "Mixed evidence" : `${n} families ${c.direction === "LONG" ? "bullish" : "bearish"}`;
  return `<span class="conf-pill ${cls}" title="${esc(c.explanation || "")}"><span class="fams">${[0, 1, 2, 3].map(k => `<i class="${k < n ? "" : "off"}"></i>`).join("")}</span>${esc(label)}</span>`;
}

// Lifecycle pips: WATCHING → ACTIVE.
export function lifecycle(stage, compact = false) {
  const idx = LIFECYCLE.indexOf(stage);
  return `<span class="life ${compact ? "compact" : ""}" title="${esc(stage)}">${LIFECYCLE.map((s, i) => `<i class="${i < idx ? "done" : i === idx ? "on s-" + s.toLowerCase() : ""}"></i>`).join("")}${compact ? "" : `<b>${esc(stage === "IDLE" ? "Idle" : stage[0] + stage.slice(1).toLowerCase())}</b>`}</span>`;
}

export const empty = (msg, sub = "") => `<div class="empty">${icon("info")}<div><b>${msg}</b>${sub ? `<p>${sub}</p>` : ""}</div></div>`;
export const unavailable = (what, reason = "") => `<div class="empty unavailable">${icon("shield")}<div><b>${what} unavailable</b><p>${esc(reason || "The engine has not provided this data.")} Nothing is shown in its place.</p></div></div>`;
export const skeleton = (rows = 3, h = 14) => `<div class="skel-wrap">${Array.from({ length: rows }, (_, i) => `<div class="skel" style="height:${h}px;width:${92 - (i % 3) * 14}%"></div>`).join("")}</div>`;
export const sourceNote = text => `<p class="source">${icon("info")}<span>${text}</span></p>`;

// Status-aware wrapper: renders skeleton / error / content for a store entry.
export function guard(entry, render, what = "Data") {
  if (!entry || entry.status === "idle" || (entry.status === "loading" && !entry.data)) return skeleton(4);
  if (!entry.data) return unavailable(what, entry.error);
  const stale = entry.status === "error" ? `<div class="stale-note">${icon("info")} Showing last data received ${ago(entry.updatedAt)} · ${esc(entry.error)}</div>` : "";
  return stale + render(entry.data);
}

// Inline SVG sparkline / area.
export function spark(values, { w = 120, h = 32, cls = "", fill = true } = {}) {
  const v = values.filter(Number.isFinite);
  if (v.length < 2) return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}"></svg>`;
  const min = Math.min(...v), max = Math.max(...v), rng = max - min || 1;
  const pts = v.map((x, i) => [(i / (v.length - 1)) * w, h - 2 - ((x - min) / rng) * (h - 4)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const t = v.at(-1) >= v[0] ? "up" : "down";
  return `<svg class="spark ${t} ${cls}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${fill ? `<path class="spark-fill" d="${d} L${w} ${h} L0 ${h}Z"/>` : ""}<path class="spark-line" d="${d}"/></svg>`;
}

// Horizontal diverging bar chart rows (value can be negative).
export function hbars(rows, { fmtV = v => fmt.num(v), max } = {}) {
  if (!rows.length) return empty("No records yet");
  const m = max ?? Math.max(...rows.map(r => Math.abs(r.value)).filter(Number.isFinite), 1e-9);
  return `<div class="hbars">${rows.map(r => {
    const w = Number.isFinite(r.value) ? Math.min(Math.abs(r.value) / m * 50, 50) : 0;
    return `<div class="hbar" ${r.title ? `title="${esc(r.title)}"` : ""}><span class="hbar-l">${r.label}</span><span class="hbar-t"><i class="${r.value >= 0 ? "pos" : "neg"}" style="width:${w}%;${r.value >= 0 ? "left:50%" : `left:${50 - w}%`}"></i><em></em></span><span class="hbar-v ${tone(r.value)}">${fmtV(r.value)}</span>${r.meta ? `<span class="hbar-m">${r.meta}</span>` : ""}</div>`;
  }).join("")}</div>`;
}

// Segmented control
export const seg = (name, options, active) => `<div class="seg" role="tablist" data-seg="${name}">${options.map(([v, l]) => `<button role="tab" data-v="${esc(v)}" class="${v === active ? "on" : ""}" aria-selected="${v === active}">${l}</button>`).join("")}</div>`;

// Toasts + notification history
const notifications = [];
let unread = 0;
const notifyListeners = new Set();
export const onNotify = fn => notifyListeners.add(fn);
export const getNotifications = () => ({ list: notifications, unread });
export function markRead() { unread = 0; notifyListeners.forEach(f => f()); }
export function toast(title, { body = "", kind = "info", record = true, ms = 5000 } = {}) {
  if (record) { notifications.unshift({ title, body, kind, at: Date.now() }); notifications.length = Math.min(notifications.length, 50); unread++; notifyListeners.forEach(f => f()); }
  if (localStorage.getItem("td_toasts") === "off" && record) return;
  let host = document.getElementById("toasts");
  if (!host) { host = document.createElement("div"); host.id = "toasts"; host.setAttribute("aria-live", "polite"); document.body.appendChild(host); }
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = `<i></i><div><b>${esc(title)}</b>${body ? `<p>${esc(body)}</p>` : ""}</div><button aria-label="Dismiss">${icon("close")}</button>`;
  el.querySelector("button").onclick = () => dismiss();
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add("in"));
  const t = setTimeout(dismiss, ms);
  function dismiss() { clearTimeout(t); el.classList.remove("in"); setTimeout(() => el.remove(), 250); }
}

// Animate numbers marked with data-num between renders.
const lastNums = new Map();
export function animateNumbers(root = document) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "off";
  root.querySelectorAll("[data-num]").forEach(el => {
    const key = el.dataset.key, to = Number(el.dataset.num), from = lastNums.get(key);
    lastNums.set(key, to);
    if (reduce || from == null || from === to || !Number.isFinite(from)) return;
    el.classList.add(to > from ? "tick-up" : "tick-down");
    setTimeout(() => el.classList.remove("tick-up", "tick-down"), 900);
  });
}

// Slide-over drawer
export function openDrawer(html, { wide = false, onClose } = {}) {
  closeDrawer();
  const el = document.createElement("div");
  el.id = "drawer";
  el.innerHTML = `<div class="drawer-bg"></div><aside class="drawer ${wide ? "wide" : ""}" role="dialog" aria-modal="true"><button class="icon-btn drawer-x" aria-label="Close">${icon("close")}</button><div class="drawer-body">${html}</div></aside>`;
  document.body.appendChild(el);
  el._onClose = onClose;
  el.querySelector(".drawer-bg").onclick = closeDrawer;
  el.querySelector(".drawer-x").onclick = closeDrawer;
  requestAnimationFrame(() => el.classList.add("in"));
  return el.querySelector(".drawer-body");
}
export function closeDrawer() {
  const el = document.getElementById("drawer");
  if (!el) return false;
  el._onClose?.();
  el.classList.remove("in");
  el.id = "";
  setTimeout(() => el.remove(), 220);
  return true;
}
