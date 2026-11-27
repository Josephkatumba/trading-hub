import * as store from "../store.mjs";
import { getEngineUrl, setEngineUrl, DEFAULT_ENGINE_URL } from "../../engine.js";
import { getBrokerTimeZone, setBrokerTimeZone } from "../../data.js";
import { isValidTimeZone } from "../../tradeTime.mjs";
import { esc, icon, panel, toast, badge, fmt } from "../ui.mjs";
import { ago } from "../model.mjs";
import { preference as themePref, setPreference as setTheme } from "../theme.mjs";

export const subtitle = "Workspace, connections and preferences";
export const need = [];
const pref = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const setPref = (k, v) => { try { localStorage.setItem(k, v); } catch {} };

export function mount(root) {
  root.innerHTML = `
    <div class="ph"><div><h1>Settings</h1><p>Preferences are stored in this browser. Credentials and API keys are never entered or shown here.</p></div></div>
    <div class="grid g-12">
      <div class="c-6">${panel({ kicker: "Connections", title: "Market engine", body: `
        <div class="set-row"><div><b>Engine URL</b><small>Local engine address. Hosted deployments use the authenticated same-origin proxy.</small></div><div class="field"><input id="stUrl" value="${esc(getEngineUrl())}" style="width:200px"></div></div>
        <div class="set-row"><div><b>Connection test</b><small id="stTest">Checks /api/health and /api/ready</small></div><button class="btn" id="stTestBtn">${icon("refresh")}Test</button></div>
        <div class="set-row"><div><b>Broker server time zone</b><small>Used to convert MT5 export times to UTC.</small></div><div class="field"><input id="stTz" value="${esc(getBrokerTimeZone())}" placeholder="e.g. Europe/Athens" style="width:160px"></div></div>
        <div class="toolbar" style="justify-content:flex-end;margin-top:8px"><button class="btn ghost" id="stReset">Reset to default</button><button class="btn primary" id="stSave">Save</button></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Diagnostics", title: "Connection status", body: `<div id="stDiag"></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Interface", title: "Preferences", body: `
        <div class="set-row"><div><b>Theme</b><small>Dark terminal, light terminal, or follow your operating system. Saved in this browser; <kbd class="k">t</kbd> toggles.</small></div>
          <div class="seg" data-seg="stTheme" role="radiogroup" aria-label="Theme">${[["dark", "moon", "Dark"], ["light", "sun", "Light"], ["system", "monitor", "System"]].map(([v, ic, l]) => `<button role="radio" data-v="${v}" class="${themePref() === v ? "on" : ""}" aria-checked="${themePref() === v}">${icon(ic)} ${l}</button>`).join("")}</div></div>
        <div class="set-row"><div><b>Toast notifications</b><small>New signals, lifecycle changes, connection events. The notification centre always records them.</small></div><label class="switch"><input type="checkbox" id="stToast" ${pref("td_toasts", "on") !== "off" ? "checked" : ""}></label></div>
        <div class="set-row"><div><b>Motion</b><small>Page transitions, ticker scroll and number flashes.</small></div><label class="switch"><input type="checkbox" id="stMotion" ${pref("td_motion", "on") !== "off" ? "checked" : ""}></label></div>
        <div class="set-row"><div><b>Collapsed sidebar by default</b><small>Toggle any time with <kbd class="k">[</kbd></small></div><label class="switch"><input type="checkbox" id="stSb" ${pref("td_sidebar", "open") === "collapsed" ? "checked" : ""}></label></div>` })}</div>
      <div class="c-6">${panel({ kicker: "Keyboard", title: "Shortcuts", body: `<div class="keys">
        <kbd class="k">1</kbd><span>… <kbd class="k">0</kbd> jump to page (Overview → Settings)</span>
        <kbd class="k">t</kbd><span>Switch between dark and light mode</span>
        <kbd class="k">/</kbd><span>Focus the page search or filter</span>
        <kbd class="k">[</kbd><span>Collapse or expand the sidebar</span>
        <kbd class="k">r</kbd><span>Refresh all engine data</span>
        <kbd class="k">Esc</kbd><span>Close panel, drawer or menu</span></div>` })}</div>
      <div class="c-12">${panel({ kicker: "Safety", title: "Execution and data integrity", body: `<div class="kv">
        <div><span>Execution</span><b id="stExec">—</b></div><div><span>Data policy</span><b style="font-size:12px">No mock or placeholder data</b></div><div><span>Signal results</span><b style="font-size:12px">Labelled hypothetical</b></div><div><span>Research results</span><b style="font-size:12px">Labelled simulated</b></div></div>
        <p class="source">${icon("shield")}<span>The terminal is read-only: it never places, modifies or closes orders. The original Garden workspace (setup archive, quant labs, journal tools) remains available at <a href="./classic.html">Classic Garden</a>.</span></p>` })}</div>
    </div>`;
  const $ = id => root.querySelector("#" + id);
  $("stSave").onclick = () => {
    const url = $("stUrl").value.trim(), tz = $("stTz").value.trim();
    if (url && !/^https?:\/\/[^\s]+$/i.test(url)) { toast("Invalid engine URL", { kind: "bad", record: false }); return; }
    if (tz && tz.toUpperCase() !== "UTC" && !isValidTimeZone(tz)) { toast("Unknown time zone", { body: tz, kind: "bad", record: false }); return; }
    setEngineUrl(url === DEFAULT_ENGINE_URL ? "" : url); setBrokerTimeZone(tz);
    toast("Settings saved", { kind: "good", record: false }); store.refreshAll();
  };
  $("stReset").onclick = () => { $("stUrl").value = DEFAULT_ENGINE_URL; };
  $("stTestBtn").onclick = async () => {
    $("stTest").textContent = "Testing…";
    const t0 = performance.now();
    await store.load("health", { force: true });
    const h = store.get("health");
    $("stTest").innerHTML = h.status === "ok" ? `<span class="up">Connected · ${Math.round(performance.now() - t0)} ms</span>` : `<span class="down">${esc(h.error)}</span>`;
  };
  const themeBtns = root.querySelectorAll('[data-seg="stTheme"] button');
  const markTheme = () => themeBtns.forEach(b => { const on = b.dataset.v === themePref(); b.classList.toggle("on", on); b.setAttribute("aria-checked", String(on)); });
  themeBtns.forEach(b => b.onclick = () => { setTheme(b.dataset.v); markTheme(); });
  $("stToast").onchange = e => setPref("td_toasts", e.target.checked ? "on" : "off");
  $("stMotion").onchange = e => { setPref("td_motion", e.target.checked ? "on" : "off"); document.documentElement.dataset.motion = e.target.checked ? "on" : "off"; };
  $("stSb").onchange = e => { setPref("td_sidebar", e.target.checked ? "collapsed" : "open"); document.getElementById("td")?.classList.toggle("collapsed", e.target.checked); };

  function diag() {
    const h = store.get("health"), d = h.data, sc = store.get("scalper");
    const row = (name, ok, detail) => `<div class="set-row"><div><b>${name}</b><small class="mono">${esc(detail)}</small></div>${badge(ok === true ? "OK" : ok === false ? "DOWN" : "—", ok === true ? "good" : ok === false ? "bad" : "muted")}</div>`;
    $("stDiag").innerHTML = [
      row("Engine API", h.status === "ok", h.status === "ok" ? `${d.service} v${d.engine_version} · ${ago(h.updatedAt)}` : h.error || "connecting"),
      row("MT5 terminal", d ? !!d.mt5_connected : null, d ? `${d.mt5_status} · build ${d.terminal?.version || "—"} · time basis ${d.source_time_basis}` : "—"),
      row("Scanner", d ? d.data_freshness?.status === "FRESH" : null, d ? `${d.scanner_status} · last scan ${ago(d.data_freshness?.last_scan_at)}` : "—"),
      row("cTrader journal", sc.data ? sc.data.heartbeat_age_seconds < 180 : sc.status === "error" ? false : null, sc.data ? `${sc.data.bot_status} · ${sc.data.account?.verification || ""}` : sc.error || "—"),
      row("Fundamentals", null, "Economic calendar: " + (store.data("fundamentals")?.status || "not loaded")),
    ].join("");
    $("stExec").innerHTML = d ? (d.execution_enabled ? '<span class="down">ENABLED</span>' : '<span class="up">Disabled</span>') : "—";
  }
  store.load("fundamentals").then(diag);
  diag();
  return { keys: ["health", "scalper"], update: diag };
}
