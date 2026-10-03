// Chooses and mounts the garden visual: a lazily loaded Three.js scene, or a
// lightweight CSS garden. Both expose the same controller: update(plants),
// select(id, labelHtml), dispose(). The page works identically with either, or
// with none at all — the visual never carries information the cards lack.
import {branchCurves, strategySectors} from "./gardenModel.mjs";

/**
 * Pure decision so it can be unit-tested. Returns "webgl" or "fallback" plus why.
 * `preference` comes from localStorage th_garden_3d ("0" forces fallback, "1" forces 3D
 * where WebGL exists).
 */
export function chooseGardenRenderer({webgl, width, saveData = false, deviceMemory = null, preference = null}) {
  if (!webgl) return {mode: "fallback", reason: "WebGL unavailable"};
  if (preference === "0") return {mode: "fallback", reason: "3D garden turned off"};
  if (preference === "1") return {mode: "webgl", reason: "3D garden forced on"};
  if (width < 720) return {mode: "fallback", reason: "Compact screen"};
  if (saveData) return {mode: "fallback", reason: "Data saver is on"};
  if (deviceMemory != null && deviceMemory <= 2) return {mode: "fallback", reason: "Low-memory device"};
  return {mode: "webgl", reason: "3D garden"};
}

export function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(window.WebGLRenderingContext && (canvas.getContext("webgl2") || canvas.getContext("webgl")));
  } catch (_) {
    return false;
  }
}

export function prefersReducedMotion() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_) { return false; }
}

function readPreference() {
  try { return localStorage.getItem("th_garden_3d"); } catch (_) { return null; }
}

export async function mountGarden(container, {onSelect = () => {}, reducedMotion = prefersReducedMotion()} = {}) {
  const decision = chooseGardenRenderer({
    webgl: webglAvailable(),
    width: window.innerWidth,             // device class, not the (narrower) stage box
    saveData: Boolean(navigator.connection?.saveData),
    deviceMemory: navigator.deviceMemory ?? null,
    preference: readPreference(),
  });
  if (decision.mode === "webgl") {
    try {
      const {createGardenScene} = await import("./gardenScene.mjs");
      const controller = createGardenScene(container, {reducedMotion, onSelect});
      return {...controller, reason: decision.reason, reducedMotion};
    } catch (error) {
      console.warn("TRADeden: 3D garden unavailable, using the 2D garden", error);
      return {...createFallbackGarden(container, {onSelect, reducedMotion}), reason: "3D failed to start"};
    }
  }
  return {...createFallbackGarden(container, {onSelect, reducedMotion}), reason: decision.reason};
}

// ----- CSS/2D constellation ------------------------------------------------------
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}[c]));
const SPAN = 6.4;   // outer archive radius in layout units
const project = (x, z, y = 0) => ({left: 50 + (x / SPAN) * 45, top: 50 + (z / SPAN) * 40 - y * 5});

export function createFallbackGarden(container, {onSelect = () => {}, reducedMotion = false} = {}) {
  const root = document.createElement("div");
  root.className = "gd-garden2d" + (reducedMotion ? " is-still" : "");
  const rings = [2.45, 4.95, 5.7].map((r, i) => '<ellipse cx="50" cy="50" rx="' + (r / SPAN * 45).toFixed(2) + '" ry="' + (r / SPAN * 40).toFixed(2)
    + '" class="gd-orbit gd-orbit-' + i + '"/>').join("");
  let seed = 11;
  const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
  const dust = Array.from({length: 26}, () => '<i class="gd-mote" style="left:' + (random() * 100).toFixed(1) + '%;top:' + (8 + random() * 84).toFixed(1)
    + '%;--d:' + (random() * 6).toFixed(2) + 's;--s:' + (0.6 + random() * 1.2).toFixed(2) + '"></i>').join("");
  root.innerHTML = '<svg class="gd-orbits" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">' + rings + '</svg>'
    + '<div class="gd-motes" aria-hidden="true">' + dust + '</div>'
    + '<svg class="gd-branches" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"></svg>'
    + '<div class="gd-sector-labels" aria-hidden="true"></div>'
    + '<div class="gd-bed" role="list" aria-label="Setups in the garden"></div>';
  container.appendChild(root);
  const bed = root.querySelector(".gd-bed");
  const branches = root.querySelector(".gd-branches"), sectorLabels = root.querySelector(".gd-sector-labels");
  let selectedId = null;
  const onClick = event => {
    const orb = event.target.closest("[data-plant-id]");
    if (orb) onSelect(orb.dataset.plantId);
  };
  bed.addEventListener("click", onClick);

  let signature = "";
  function update(orbs) {
    const next = JSON.stringify(orbs.map(o => [o.id, o.stage, o.direction, o.strategy, o.x.toFixed(2), o.z.toFixed(2)]));
    if (next === signature) return select(selectedId);   // unchanged: keep float phases running
    signature = next;
    const parent = container.parentElement;
    const overlaid = parent && getComputedStyle(parent).position === "absolute" && root.clientWidth / Math.max(1, root.clientHeight) > 1.6;
    const place = (x, z, y = 0) => { const q = project(x, z, y); return overlaid ? {left: 62 + (q.left - 50) * 0.72, top: q.top} : q; };
    // Strategy structure: a trunk per strategy and a branch to each of its live setups.
    const trunks = strategySectors(orbs).map(sector => {
      const a = place(0, 0), b = place(Math.cos(sector.angle) * 0.7, Math.sin(sector.angle) * 0.7);
      const label = place(Math.cos(sector.angle) * 5.25, Math.sin(sector.angle) * 5.25);
      return {sector, path: 'M' + a.left.toFixed(2) + ' ' + a.top.toFixed(2) + 'L' + b.left.toFixed(2) + ' ' + b.top.toFixed(2), label};
    });
    branches.innerHTML = trunks.map(t => '<path class="gd-trunk" style="stroke:' + t.sector.color + '" d="' + t.path + '"/>').join("")
      + branchCurves(orbs).map(curve => {
        const h = place(curve.hub.x, curve.hub.z), c = place(curve.control.x, curve.control.z), e = place(curve.end.x, curve.end.z, curve.end.y);
        return '<path class="gd-branch gd-branch-' + curve.stage + '" style="stroke:' + curve.color + '" d="M' + h.left.toFixed(2) + ' ' + h.top.toFixed(2)
          + 'Q' + c.left.toFixed(2) + ' ' + c.top.toFixed(2) + ' ' + e.left.toFixed(2) + ' ' + e.top.toFixed(2) + '"/>';
      }).join("");
    sectorLabels.innerHTML = trunks.map(t => '<span class="gd-sector-label" data-strategy="' + esc(t.sector.id) + '" style="left:' + t.label.left.toFixed(1) + '%;top:' + t.label.top.toFixed(1) + '%">'
      + '<i class="gd-glyph"></i>' + esc(t.sector.tag) + '</span>').join("");
    bed.innerHTML = orbs.map(orb => {
      const projected = project(orb.x, orb.z, orb.y);
      const left = overlaid ? 62 + (projected.left - 50) * 0.72 : projected.left, top = projected.top;
      const depth = (orb.z / SPAN + 1) / 2;                 // 0 = back, 1 = front
      return '<button type="button" role="listitem" data-strategy="' + esc(orb.strategy || "") + '" class="gd-orb2d gd-o-' + orb.stage + ' gd-o-' + String(orb.direction || "none").toLowerCase() + (orb.outcome ? ' gd-out-' + orb.outcome : '')
        + (orb.id === selectedId ? ' is-selected' : '') + '" data-plant-id="' + esc(orb.id) + '" aria-label="' + esc(orb.symbol + " · " + orb.stage) + '"'
        + ' style="left:' + left.toFixed(1) + '%;top:' + top.toFixed(1) + '%;--k:' + (0.8 + depth * 0.35).toFixed(2) + ';--d:' + (orb.phase % 4).toFixed(2) + 's;z-index:' + Math.round(depth * 100) + '">'
        + '<span class="gd-o-body"></span><span class="gd-o-label">' + esc(orb.symbol) + '</span></button>';
    }).join("");
  }

  function select(id) {
    selectedId = id;
    for (const node of bed.querySelectorAll("[data-plant-id]")) node.classList.toggle("is-selected", node.dataset.plantId === id);
  }

  function dispose() {
    bed.removeEventListener("click", onClick);
    root.remove();
  }

  return {kind: "fallback", update, select, dispose};
}
