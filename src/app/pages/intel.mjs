// Renderers for the engine's ICT context and strategy confluence
// (GET /api/intelligence/market). Every number shown comes from the payload;
// a missing payload renders as unavailable, never as a placeholder value.
import { esc, fmt, icon, badge, empty, tierBadge, stageBadge } from "../ui.mjs";

export const SHORT = {
  ict_sweep_reversal: "Sweep reversal", ict_mss: "MSS", ict_fvg_continuation: "FVG continuation", ict_ob_reversal: "OB reversal",
  ict_ote: "OTE", ict_silver_bullet: "Silver Bullet", ict_judas: "Judas swing", ict_sweep_fvg: "Sweep + FVG",
  trendline_v5: "Trendline", support_resistance: "S/R levels", trend_momentum: "Trend momentum", smc: "SMC",
};
const dirWord = d => d === "LONG" ? '<span class="up">bullish</span>' : d === "SHORT" ? '<span class="down">bearish</span>' : "neutral";
const tone3 = v => v === "BULLISH" ? "up" : v === "BEARISH" ? "down" : "muted";

export function structureHtml(ict) {
  const s = ict.structure || {};
  return `<div class="tfstruct">${["M15", "H1", "H4"].map(tf => `<div><span>${tf} STRUCTURE${tf === "H4" ? " · BIAS" : ""}</span><b class="${tone3(s[tf])}">${esc(s[tf] || "—")}</b></div>`).join("")}</div>`;
}

export function dealingHtml(ict, P) {
  const d = ict.dealing_range;
  if (!d) return empty("No H1 dealing range", "Needs a confirmed H1 swing high and swing low.");
  const pos = Math.max(0, Math.min(1, d.position));
  const span = d.high - d.low;
  const [a, b] = d.leg === "UP" ? d.ote_long : d.ote_short;
  const l = Math.max(0, (Math.min(a, b) - d.low) / span), r = Math.min(1, (Math.max(a, b) - d.low) / span);
  return `<div class="zone-bar" title="Price at ${(pos * 100).toFixed(0)}% of the H1 range"><div class="zb-d"></div><div class="zb-p"></div><div class="zb-ote" style="left:${l * 100}%;width:${(r - l) * 100}%"></div><div class="zb-eq"></div><div class="zb-px" style="left:${pos * 100}%"></div></div>
    <div class="zone-lbl"><span>Low ${P(d.low)} · discount</span><span>EQ ${P(d.equilibrium)}</span><span>premium · high ${P(d.high)}</span></div>
    <p class="dsub" style="margin:8px 0 0">Price is in <b class="${d.zone === "DISCOUNT" ? "up" : d.zone === "PREMIUM" ? "down" : ""}">${esc(d.zone.toLowerCase())}</b> (${(pos * 100).toFixed(0)}% of the range). Last leg ${d.leg === "UP" ? "up" : "down"}; hatched band = OTE (62–79% retracement) for a ${d.leg === "UP" ? "long" : "short"}.</p>`;
}

export function ladderHtml(ict, P) {
  const pools = (ict.liquidity || []).filter(p => p.kind !== "SWING_H" && p.kind !== "SWING_L" || !p.swept);
  if (!pools.length) return empty("No liquidity pools identified");
  const rows = [...pools].sort((a, b) => b.price - a.price);
  const k = rows.findIndex(p => p.price < ict.price);
  const now = `<div class="lad now"><span class="side">PRICE</span><span class="nm">Last close</span><span>${P(ict.price)}</span><span class="dist"></span></div>`;
  const row = p => `<div class="lad ${p.swept ? "swept" : ""}"><span class="side ${p.side.toLowerCase()}">${p.side}</span><span class="nm">${esc(p.label)}</span><span>${P(p.price)}</span><span class="dist">${p.distance_atr == null ? "" : (p.distance_atr > 0 ? "+" : "") + p.distance_atr.toFixed(1) + " ATR"}</span></div>`;
  const html = rows.map(row);
  html.splice(k < 0 ? html.length : k, 0, now);
  return `<div class="ladder">${html.join("")}</div><p class="source">${icon("info")}<span>BSL = buy-side liquidity (stops above highs), SSL = sell-side (below lows). A pool is swept once traded through; distances in M15 ATR.</span></p>`;
}

export function zonesHtml(ict, P) {
  const g = (ict.fvgs || []).map(f => `<div class="zrow ${f.direction === "BULLISH" ? "bull" : "bear"}"><span class="t">${f.direction === "BULLISH" ? "Bullish" : "Bearish"} FVG · M15 · ${esc(f.status.toLowerCase())}${f.ce_touched ? " · CE reached" : ""}</span><span>${P(f.bottom)} – ${P(f.top)}</span><span class="muted">${fmt.time(f.formed_at)}</span></div>`);
  const o = (ict.order_blocks || []).slice(0, 5).map(b => `<div class="zrow ${/BULLISH/.test(b.type) ? "bull" : "bear"}"><span class="t">${esc(b.type.toLowerCase())} · H1 · ${esc(b.state.toLowerCase())}</span><span>${P(b.low)} – ${P(b.high)}</span><span class="muted">${fmt.dt(b.formed_at).slice(5)}</span></div>`);
  return g.length || o.length ? `<div class="zones">${g.concat(o).join("")}</div>` : empty("No open fair value gaps or order blocks", "Gaps need a displacement candle; blocks need a structure break.");
}

export function setupsHtml(setups, P, { all = false } = {}) {
  const rows = (setups || []).filter(s => all || s.stage !== "NONE");
  if (!rows.length) return empty("No ICT setup is forming", "All eight setups are idle on the last closed M15 bar.");
  return `<div class="setups">${rows.map(s => `<div class="setup" data-s="${esc(s.stage)}"><header><b>${esc(s.name)}</b><span style="display:flex;gap:5px;align-items:center">${s.direction ? badge(s.direction === "LONG" ? "Bullish" : "Bearish", s.direction === "LONG" ? "good" : "bad") : ""}${stageBadge(s.stage)}${s.tier ? tierBadge(s.tier) : ""}</span></header>
    <ul>${(s.evidence || []).map(e => `<li>${esc(e)}</li>`).join("")}${(s.missing || []).map(m => `<li class="miss">Needs: ${esc(m)}</li>`).join("")}${s.blocked ? `<li class="blk">Blocked: ${esc(s.blocked)}</li>` : ""}</ul>
    ${s.invalidation != null ? `<div class="inv">Invalidation ${P(s.invalidation)}${s.levels?.target ? ` · stop ${P(s.levels.stop)} · target ${P(s.levels.target)}` : ""}</div>` : ""}</div>`).join("")}</div>`;
}

export function confluenceHtml(c) {
  if (!c) return empty("Confluence unavailable");
  const fams = (c.families || []).map(f => `<div class="fam ${f.direction ? f.direction.toLowerCase() : "conflict"}"><header><span>${esc(f.label)}</span>${f.direction ? badge(f.direction === "LONG" ? "Bullish" : "Bearish", f.direction === "LONG" ? "good" : "bad") : badge("Conflicted", "warn")}</header>
    <p>${f.members.map(m => `${esc(SHORT[m.key] || m.name)} · ${esc(String(m.stage).toLowerCase())}${m.confirmed_entry ? " · <b class=\"up\">confirmed entry</b>" : ""}`).join("<br>")}</p></div>`).join("");
  const cls = { "CONFIRMED CONFLUENCE": "good", "DIRECTIONAL AGREEMENT": "info", MIXED: "warn", NONE: "muted" }[c.classification] || "muted";
  return `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">${badge(c.classification, cls)}${c.direction ? `<span class="muted" style="font-size:12px">${c.independent_families} independent famil${c.independent_families === 1 ? "y" : "ies"} ${dirWord(c.direction)}${c.opposing_families ? ` · ${c.opposing_families} against` : ""}</span>` : ""}</div>
    <p class="prose">${esc(c.explanation)}</p>
    ${c.caveat ? `<div class="banner" style="margin:10px 0 0">${icon("info")}<div>${esc(c.caveat)}</div></div>` : ""}
    ${fams ? `<div class="fam-grid" style="margin-top:10px">${fams}</div>` : ""}
    <p class="source">${icon("info")}<span>${esc(c.method)} Strategies that read the same evidence (e.g. three sweep-based ICT setups) count as one family.</span></p>`;
}

// Full ICT section for drawers.
export function ictSection(res, symbol, digits) {
  if (!res?.ok) return empty("ICT context unavailable", res?.error || "");
  const P = v => fmt.price(v, symbol, digits);
  const ict = res.ict;
  return `<p class="dsub">Closed M15 bar ${fmt.dt(ict.bar_closed_at)} UTC · New York ${esc(ict.ny_time)}${ict.kill_zone ? ` · <b class="ai">${esc(ict.kill_zone)}</b>` : ""} · ${esc(res.mode)}</p>
    ${structureHtml(ict)}
    <div class="dsec"><h3 class="ai">${icon("analyst")}Setup progression · ICT family</h3>${setupsHtml(ict.setups, P)}</div>
    <div class="dsec"><h3>Strategy confluence</h3>${confluenceHtml(res.confluence)}</div>
    <div class="dsec"><h3>Premium / discount · H1 dealing range</h3>${dealingHtml(ict, P)}</div>
    <div class="dsec"><h3>Liquidity map</h3>${ladderHtml(ict, P)}</div>
    <div class="dsec"><h3>Fair value gaps & order blocks</h3>${zonesHtml(ict, P)}</div>`;
}
