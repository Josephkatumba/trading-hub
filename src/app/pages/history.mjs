import { engineFetch } from "../../engine.js";
import { esc, fmt, tone, icon, dir, badge, empty, seg, stat, openDrawer, toast, sourceNote } from "../ui.mjs";
import { sortRows } from "../model.mjs";
import { getTrades, saveTrades, parseCSV, normalizeTrades, getBrokerTimeZone, setBrokerTimeZone, calculateMetrics, getTradeContext } from "../../data.js";
import { mergeImportedTrades } from "../../tradeImport.mjs";
import { isValidTimeZone } from "../../tradeTime.mjs";
import { getReview, saveReview, DEFAULT_RULES } from "../../journal.js";

export const subtitle = "Executed trade ledger and journal";
export const need = [];

export function mount(root) {
  const st = { src: "journal", q: "", symbol: "", account: "", side: "", result: "", sort: "time", dir: "desc" };
  let trades = getTrades(), ctrader = null;
  root.innerHTML = `
    <div class="ph"><div><h1>Trade History</h1><p>Every executed trade from your journal imports and the cTrader bot journal. Click a trade to review it.</p></div>
      <div class="ph-a">${seg("thSrc", [["journal", "Journal"], ["ctrader", "cTrader bot"]], st.src)}<button class="btn primary" id="thImport">${icon("upload")}Import CSV</button></div></div>
    <div id="thStats"></div><div class="toolbar mt" id="thTools"></div>
    <section class="panel flush mt"><div class="tbl-wrap" id="thTable" style="max-height:calc(100vh - 330px);min-height:300px"></div><div class="tbl-foot" id="thFoot"></div></section>`;
  const $ = id => root.querySelector("#" + id);
  root.querySelectorAll('[data-seg="thSrc"] button').forEach(b => b.onclick = () => { st.src = b.dataset.v; root.querySelectorAll('[data-seg="thSrc"] button').forEach(x => x.classList.toggle("on", x === b)); draw(); });
  $("thImport").onclick = openImport;

  const rows = () => st.src === "journal"
    ? trades.map(t => ({ id: t.id, time: Date.parse(String(t.time_utc || t.time).replace(" ", "T") + (t.time_utc ? "" : "Z")), timeText: t.time, symbol: t.symbol, side: t.side, account: t.account, entry: t.entry, exit: t.exit, volume: t.volume, pnl: Number(t.pnl), r: t.r, session: t.session, raw: t }))
    : (ctrader || []).map((t, i) => ({ id: t.position_id || t.id || "ct" + i, time: Date.parse(t.close_time || t.closed_at || t.ts), timeText: fmt.dt(t.close_time || t.closed_at || t.ts), symbol: t.symbol, side: t.side || t.direction, account: "cTrader demo", entry: t.entry_price ?? t.entry, exit: t.exit_price ?? t.exit, volume: t.volume ?? t.lots, pnl: Number(t.net_pnl ?? t.pnl ?? t.net_profit), r: t.r_multiple ?? t.r, session: t.session || "—", raw: t }));

  function filtered() {
    return rows().filter(r => (!st.symbol || r.symbol === st.symbol) && (!st.account || r.account === st.account) && (!st.side || r.side === st.side) &&
      (!st.result || (st.result === "WIN" ? r.pnl > 0 : r.pnl < 0)) && (!st.q || [r.symbol, r.account, r.side, r.session, r.id].join(" ").toUpperCase().includes(st.q)));
  }
  function tools() {
    const all = rows();
    const opt = (vals, cur, label) => `<option value="">${label}</option>` + [...new Set(vals)].filter(Boolean).sort().map(v => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
    $("thTools").innerHTML = `<div class="field">${icon("search")}<input data-search id="thQ" value="${esc(st.q)}" placeholder="Search trades  /" autocomplete="off"></div>
      <select class="sel" data-k="symbol">${opt(all.map(r => r.symbol), st.symbol, "All instruments")}</select>
      <select class="sel" data-k="account">${opt(all.map(r => r.account), st.account, "All accounts")}</select>
      <select class="sel" data-k="side"><option value="">Both sides</option><option ${st.side === "BUY" ? "selected" : ""}>BUY</option><option ${st.side === "SELL" ? "selected" : ""}>SELL</option></select>
      <select class="sel" data-k="result"><option value="">Any result</option><option value="WIN" ${st.result === "WIN" ? "selected" : ""}>Winners</option><option value="LOSS" ${st.result === "LOSS" ? "selected" : ""}>Losers</option></select>`;
    $("thQ").oninput = e => { st.q = e.target.value.trim().toUpperCase(); drawTable(); };
    $("thTools").querySelectorAll("[data-k]").forEach(s => s.onchange = () => { st[s.dataset.k] = s.value; drawTable(); });
  }
  function drawTable() {
    const list = sortRows(filtered(), st.sort, st.dir);
    const m = calculateMetrics(list.map(r => ({ pnl: r.pnl, time: r.timeText, symbol: r.symbol, session: r.session })));
    $("thStats").innerHTML = `<div class="stats s5">${stat({ label: "Trades", value: list.length, sub: st.src === "journal" ? "Journal" : "cTrader bot" })}${stat({ label: "Net P&L", value: `<span class="${tone(m.pnl)}">${fmt.money(m.pnl, "USD", true)}</span>` })}${stat({ label: "Win rate", value: list.length ? fmt.pct(m.winRate, 1, false) : "—", sub: `${m.wins}W · ${m.losses}L` })}${stat({ label: "Profit factor", value: fmt.num(m.profitFactor, 2) })}${stat({ label: "Best instrument", value: `<span style="font-size:15px">${esc(m.bestInstrument)}</span>` })}</div>`;
    if (st.src === "ctrader" && ctrader === null) { $("thTable").innerHTML = `<div class="empty">${icon("refresh")}<div><b>Loading cTrader trades…</b></div></div>`; return; }
    if (!list.length) { $("thTable").innerHTML = st.src === "ctrader" ? empty(ctrader?.error ? "cTrader trades unavailable" : "No closed cTrader bot trades yet", ctrader?.error || "The demo bot has not closed any trades.") : empty(trades.length ? "No trades match these filters" : "No trades in your journal", trades.length ? "" : "Import an MT5 or broker CSV to begin."); $("thFoot").innerHTML = ""; return; }
    const C = [["time", "Time"], ["symbol", "Instrument"], ["side", "Side"], ["account", "Account"], ["session", "Session"], ["volume", "Volume", "r"], ["entry", "Entry", "r"], ["exit", "Exit", "r"], ["pnl", "P&L", "r"]];
    $("thTable").innerHTML = `<table class="tbl"><thead><tr>${C.map(([k, l, a]) => `<th class="sort ${a || ""} ${st.sort === k ? "sorted" : ""}" data-sort="${k}">${l}${st.sort === k ? (st.dir === "asc" ? " ↑" : " ↓") : ""}</th>`).join("")}</tr></thead><tbody>
      ${list.map(r => `<tr class="click" data-id="${esc(r.id)}"><td class="num muted">${esc(r.timeText)}</td><td class="sym">${esc(r.symbol)}</td><td>${dir(r.side)}</td><td>${esc(r.account)}</td><td class="muted">${esc(r.session)}</td><td class="r">${fmt.num(r.volume, 2)}</td><td class="r">${fmt.price(r.entry, r.symbol)}</td><td class="r">${fmt.price(r.exit, r.symbol)}</td><td class="r ${tone(r.pnl)}">${fmt.money(r.pnl, "USD", true)}</td></tr>`).join("")}</tbody></table>`;
    $("thFoot").innerHTML = `<span>${list.length} of ${rows().length} trades</span><span>${st.src === "journal" ? "Stored " + (trades.length ? "in this workspace" : "—") : "From the cTrader journal (demo)"}</span>`;
    $("thTable").querySelectorAll("[data-sort]").forEach(th => th.onclick = () => { if (st.sort === th.dataset.sort) st.dir = st.dir === "asc" ? "desc" : "asc"; else { st.sort = th.dataset.sort; st.dir = "desc"; } drawTable(); });
    $("thTable").querySelectorAll("[data-id]").forEach(tr => tr.onclick = () => openTrade(list.find(r => String(r.id) === tr.dataset.id)));
  }

  function openTrade(r) {
    if (!r) return;
    const isJ = st.src === "journal", t = r.raw;
    const c = isJ ? getTradeContext(t, trades) : null, review = isJ ? getReview(t.id) : null;
    const body = openDrawer(`<div class="dh"><h2>${esc(r.symbol)}</h2>${dir(r.side)}${badge(r.pnl > 0 ? "WIN" : r.pnl < 0 ? "LOSS" : "FLAT", r.pnl > 0 ? "good" : r.pnl < 0 ? "bad" : "muted")}</div>
      <p class="dsub">${esc(r.timeText)} · ${esc(r.account)} · ${esc(r.session)} · ${esc(r.id)}</p>
      <div class="kv"><div><span>P&L</span><b class="${tone(r.pnl)}">${fmt.money(r.pnl, "USD", true)}</b></div><div><span>Entry</span><b>${fmt.price(r.entry, r.symbol)}</b></div><div><span>Exit</span><b>${fmt.price(r.exit, r.symbol)}</b></div><div><span>Volume</span><b>${fmt.num(r.volume, 2)}</b></div><div><span>R multiple</span><b>${r.r ? fmt.r(Number(r.r)) : '<span class="na">Not recorded</span>'}</b></div></div>
      ${isJ ? `<p class="source">${icon("info")}<span>${t.time_status === "VERIFIED" ? "UTC " + esc(String(t.time_utc).slice(0, 16).replace("T", " ")) + " · basis " + esc(t.time_basis) : "Time basis unverified — session not classified. Set the broker time zone when importing."}</span></p>
      <div class="dsec"><h3>Your ${esc(r.symbol)} history</h3><div class="kv"><div><span>Trades</span><b>${c.symbolTrades}</b></div><div><span>Win rate</span><b>${fmt.pct(c.symbolWinRate, 1, false)}</b></div><div><span>Net P&L</span><b class="${tone(c.symbolPnl)}">${fmt.money(c.symbolPnl, "USD", true)}</b></div></div></div>
      <div class="dsec"><h3>Post-trade review</h3>
        <div class="toolbar"><select class="sel" id="rvSetup"><option value="">Setup</option>${["Trendline reversal", "Breakout", "Retest", "Range reversal", "Other"].map(s => `<option ${review.setup === s ? "selected" : ""}>${s}</option>`).join("")}</select><select class="sel" id="rvGrade"><option value="">Execution grade</option>${["A", "B", "C", "D"].map(g => `<option ${review.grade === g ? "selected" : ""}>${g}</option>`).join("")}</select></div>
        <div style="display:flex;flex-direction:column;gap:6px;margin:10px 0">${DEFAULT_RULES.map((rule, i) => `<label class="switch"><input type="checkbox" data-rule="${i}" ${review.rules?.includes(i) ? "checked" : ""}>${esc(rule)}</label>`).join("")}</div>
        <textarea id="rvNotes" rows="4" style="width:100%;background:var(--bg2);border:1px solid var(--line2);border-radius:6px;padding:9px;color:var(--t1)" placeholder="What did you see? What would you repeat or change?">${esc(review.notes || "")}</textarea>
        <div class="toolbar" style="margin-top:8px;justify-content:space-between"><small class="muted">${review.updatedAt ? "Saved " + fmt.dt(review.updatedAt) : "Not reviewed yet"}</small><button class="btn primary" id="rvSave">Save review</button></div></div>` : `<div class="dsec"><h3>Raw record</h3><pre class="mono" style="font-size:11px;color:var(--t3);white-space:pre-wrap">${esc(JSON.stringify(t, null, 2))}</pre></div>`}`);
    const save = body.querySelector("#rvSave");
    if (save) save.onclick = async () => {
      try {
        await saveReview(t.id, { setup: body.querySelector("#rvSetup").value, grade: body.querySelector("#rvGrade").value, rules: [...body.querySelectorAll("[data-rule]:checked")].map(x => Number(x.dataset.rule)), notes: body.querySelector("#rvNotes").value });
        toast("Review saved", { kind: "good", record: false });
      } catch { toast("Review not saved", { body: "Reload and retry.", kind: "bad", record: false }); }
    };
  }

  function openImport() {
    const bg = document.createElement("div");
    bg.className = "modal-bg";
    bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true"><h3>Import trades</h3><p class="dsub">CSV export from MT5, a broker, prop firm or futures platform. Parsed locally in your browser; duplicates are skipped.</p>
      <label class="kicker" for="imTz">Broker server time zone</label><div class="field" style="width:100%"><input id="imTz" value="${esc(getBrokerTimeZone())}" placeholder="e.g. Europe/Athens or UTC — leave empty if unknown" style="width:100%"></div>
      <p class="source">${icon("info")}<span>MT5 exports use broker server time. Sessions stay “Unverified” until this is set; TRADEDEN never guesses it.</span></p>
      <label class="drop" id="imDrop"><input type="file" id="imFile" accept=".csv,text/csv,.txt">${icon("upload")}<br><b>Drop CSV here or click to browse</b></label><div id="imStatus" class="dsub"></div>
      <div class="toolbar" style="justify-content:flex-end"><button class="btn ghost" id="imClose">Close</button></div></div>`;
    document.body.appendChild(bg);
    const close = () => bg.remove();
    bg.onclick = e => { if (e.target === bg) close(); };
    bg.querySelector("#imClose").onclick = close;
    const drop = bg.querySelector("#imDrop");
    drop.ondragover = e => { e.preventDefault(); drop.classList.add("drag"); };
    drop.ondragleave = () => drop.classList.remove("drag");
    drop.ondrop = e => { e.preventDefault(); drop.classList.remove("drag"); if (e.dataTransfer.files[0]) handle(e.dataTransfer.files[0]); };
    bg.querySelector("#imFile").onchange = e => { if (e.target.files[0]) handle(e.target.files[0]); };
    async function handle(file) {
      const status = bg.querySelector("#imStatus"), tz = bg.querySelector("#imTz").value.trim();
      if (tz && tz.toUpperCase() !== "UTC" && !isValidTimeZone(tz)) { status.innerHTML = `<span class="down">"${esc(tz)}" is not a recognised IANA time zone.</span>`; return; }
      setBrokerTimeZone(tz);
      status.textContent = "Reading " + file.name + "…";
      const parsed = parseCSV(await file.text(), { sourceTimeZone: tz });
      if (!parsed.length) { status.innerHTML = `<span class="down">No recognisable executions found. Expected columns such as Symbol, Side, Entry, Exit, Volume, P&L.</span>`; return; }
      const res = mergeImportedTrades(trades, parsed);
      try { await saveTrades(normalizeTrades(res.trades)); trades = getTrades(); }
      catch { status.innerHTML = `<span class="down">Import was not saved. Existing records are preserved; reload and retry.</span>`; return; }
      const skipped = res.skippedExistingId + res.skippedDuplicateContent;
      status.innerHTML = `<span class="up">Added ${res.added} trade${res.added === 1 ? "" : "s"}.</span>${skipped ? ` ${skipped} duplicates skipped.` : ""}`;
      toast("Trades imported", { body: `${res.added} added from ${file.name}`, kind: "good" });
      draw();
    }
  }

  function draw() {
    tools(); drawTable();
    if (st.src === "ctrader" && ctrader === null) engineFetch("/api/scalper/trades?limit=500").then(d => { ctrader = d.trades || []; }).catch(e => { ctrader = []; ctrader.error = e?.status === 403 ? "Only available on the local owner machine" : "cTrader journal endpoint unreachable"; }).finally(() => { if (root.isConnected && st.src === "ctrader") draw(); });
  }
  draw();
  return {};
}
