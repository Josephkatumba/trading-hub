// TradingView Lightweight Charts wrappers, themed for the terminal. Every
// series is fed real engine candles or recorded results only.
import { ema, rsi, atr } from "./indicators.mjs";
import { priceDigits } from "./model.mjs";

let lib = null, libPromise = null;
const loadLib = async () => lib || (lib = await (libPromise ||= import("lightweight-charts")));

// Colours come from the active theme's CSS tokens (app.css), read when a chart is
// built; main.mjs re-mounts the page on a theme change so charts redraw.
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
// Translucent variant of a token colour (lightweight-charts needs rgba, not color-mix).
export function alpha(color, a) {
  const m = /^#([0-9a-f]{6})$/i.exec(color || "");
  if (m) { const n = parseInt(m[1], 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }
  const r = /^rgba?\(([^)]+)\)$/i.exec(color || "");
  if (r) { const [x, y, z] = r[1].split(",").map(v => v.trim()); return `rgba(${x},${y},${z},${a})`; }
  return color;
}
export const C = () => ({
  up: css("--up") || "#2fd59a", down: css("--down") || "#ff6b7d", text: css("--t3") || "#7e8ba5",
  grid: css("--grid") || "rgba(138,160,204,.05)", line: css("--line") || "rgba(138,160,204,.11)", accent: css("--accent") || "#4f9dff",
  amber: css("--amber") || "#f6b94a", violet: css("--violet") || "#a98bff",
  crosshair: css("--chart-crosshair") || "rgba(140,160,190,.35)", label: css("--chart-label") || "#1b2433",
});

function base(el, extra = {}) {
  const c = C();
  return lib.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: c.text, fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: 10, attributionLogo: true, panes: { separatorColor: c.line, separatorHoverColor: c.accent, enableResize: true } },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    rightPriceScale: { borderColor: c.line },
    timeScale: { borderColor: c.line, timeVisible: true, secondsVisible: false },
    crosshair: { mode: 0, vertLine: { color: c.crosshair, labelBackgroundColor: c.label }, horzLine: { color: c.crosshair, labelBackgroundColor: c.label } },
    ...extra,
  });
}

// Monotonic seconds for line data built from millisecond timestamps.
export function lineData(points) {
  let prev = -Infinity;
  return points.map(p => {
    let t = Math.floor(p.t / 1000);
    if (t <= prev) t = prev + 1;
    prev = t;
    return { time: t, value: p.value };
  });
}

export async function candleChart(el, { candles, symbol, digits, emas = [20, 50], levels = [], plan = null, markers = [], volume = true, showRSI = true, showATR = false }) {
  await loadLib();
  if (!el.isConnected) return null;
  const c = C();
  const prec = priceDigits(symbol, candles.at(-1)?.close, digits);
  const chart = base(el);
  const series = chart.addSeries(lib.CandlestickSeries, {
    upColor: c.up, downColor: c.down, borderVisible: false, wickUpColor: c.up, wickDownColor: c.down,
    priceFormat: { type: "price", precision: prec, minMove: 1 / 10 ** prec },
  });
  series.setData(candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
  const closes = candles.map(k => k.close);

  const hasVol = volume && candles.some(k => Number.isFinite(k.volume) && k.volume > 0);
  if (hasVol) {
    const v = chart.addSeries(lib.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    v.setData(candles.map(k => ({ time: k.time, value: k.volume || 0, color: k.close >= k.open ? alpha(c.up, 0.28) : alpha(c.down, 0.28) })));
  }

  const emaColors = [c.amber, c.violet, c.accent];
  emas.forEach((n, i) => {
    const vals = ema(closes, n);
    const s = chart.addSeries(lib.LineSeries, { color: emaColors[i % 3], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: "EMA" + n });
    s.setData(candles.map((k, j) => vals[j] == null ? null : { time: k.time, value: vals[j] }).filter(Boolean));
  });

  for (const l of levels) {
    series.createPriceLine({ price: l.price, color: l.type === "RESISTANCE" ? alpha(c.down, 0.55) : alpha(c.up, 0.55), lineWidth: 1, lineStyle: 3, axisLabelVisible: false, title: (l.type === "RESISTANCE" ? "R" : "S") + (l.touches > 1 ? "×" + l.touches : "") });
  }
  if (plan) {
    const line = (price, color, title, style = 2) => Number.isFinite(Number(price)) && series.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    line(plan.entry, c.accent, "Entry", 0);
    line(plan.stop, c.down, "SL");
    line(plan.target, c.up, "TP");
  }
  if (markers.length) lib.createSeriesMarkers(series, markers.filter(m => m.time >= candles[0].time).sort((a, b) => a.time - b.time));

  let pane = 1;
  if (showRSI) {
    const vals = rsi(closes, 14);
    const s = chart.addSeries(lib.LineSeries, { color: c.violet, lineWidth: 1, priceLineVisible: false, title: "RSI 14", priceFormat: { type: "price", precision: 1, minMove: 0.1 } }, pane);
    s.setData(candles.map((k, j) => vals[j] == null ? null : { time: k.time, value: vals[j] }).filter(Boolean));
    s.createPriceLine({ price: 70, color: alpha(c.down, 0.35), lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
    s.createPriceLine({ price: 30, color: alpha(c.up, 0.35), lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
    pane++;
  }
  if (showATR) {
    const vals = atr(candles, 14);
    const s = chart.addSeries(lib.LineSeries, { color: c.amber, lineWidth: 1, priceLineVisible: false, title: "ATR 14", priceFormat: { type: "price", precision: prec, minMove: 1 / 10 ** prec } }, pane);
    s.setData(candles.map((k, j) => vals[j] == null ? null : { time: k.time, value: vals[j] }).filter(Boolean));
    pane++;
  }
  try { const panes = chart.panes(); for (let i = 1; i < panes.length; i++) panes[i].setHeight(Math.round(el.clientHeight * 0.18)); } catch {}
  chart.timeScale().fitContent();
  if (candles.length > 160) chart.timeScale().setVisibleLogicalRange({ from: candles.length - 160, to: candles.length + 4 });
  return { chart, series, destroy: () => chart.remove() };
}

// Cumulative value over time; green above zero, red below.
// Static (non-price) charts keep the page scrollable: no wheel zoom/scroll.
const STATIC = { handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: false, vertTouchDrag: false }, handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true } };

export async function equityChart(el, points, { precision = 2, unit = "" } = {}) {
  await loadLib();
  if (!el.isConnected || !points.length) return null;
  const c = C();
  const chart = base(el, { ...STATIC, rightPriceScale: { borderColor: c.line, scaleMargins: { top: 0.12, bottom: 0.08 } } });
  const s = chart.addSeries(lib.BaselineSeries, {
    baseValue: { type: "price", price: 0 },
    topLineColor: c.up, topFillColor1: alpha(c.up, 0.28), topFillColor2: alpha(c.up, 0.02),
    bottomLineColor: c.down, bottomFillColor1: alpha(c.down, 0.02), bottomFillColor2: alpha(c.down, 0.28),
    lineWidth: 2, priceFormat: { type: "custom", minMove: 1 / 10 ** precision, formatter: v => v.toFixed(precision) + unit },
  });
  s.setData(lineData(points));
  chart.timeScale().fitContent();
  return { chart, destroy: () => chart.remove() };
}

export async function drawdownChart(el, points, { precision = 2, unit = "" } = {}) {
  await loadLib();
  if (!el.isConnected || !points.length) return null;
  const c = C();
  const chart = base(el, STATIC);
  const s = chart.addSeries(lib.AreaSeries, { lineColor: c.down, topColor: alpha(c.down, 0.05), bottomColor: alpha(c.down, 0.35), lineWidth: 1, invertFilledArea: true, priceFormat: { type: "custom", minMove: 1 / 10 ** precision, formatter: v => v.toFixed(precision) + unit } });
  s.setData(lineData(points));
  chart.timeScale().fitContent();
  return { chart, destroy: () => chart.remove() };
}

// Daily bars (time in seconds, value signed).
export async function barChart(el, bars, { precision = 2, unit = "" } = {}) {
  await loadLib();
  if (!el.isConnected || !bars.length) return null;
  const c = C();
  const chart = base(el, { ...STATIC, timeScale: { borderColor: c.line, timeVisible: false } });
  const s = chart.addSeries(lib.HistogramSeries, { priceFormat: { type: "custom", minMove: 1 / 10 ** precision, formatter: v => v.toFixed(precision) + unit } });
  s.setData(bars.map(b => ({ time: b.time, value: b.value, color: b.value >= 0 ? alpha(c.up, 0.75) : alpha(c.down, 0.75) })));
  chart.timeScale().fitContent();
  return { chart, destroy: () => chart.remove() };
}
