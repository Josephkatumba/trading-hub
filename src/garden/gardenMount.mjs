// Chooses and mounts the garden visual: a lazily loaded Three.js scene, or a
// lightweight CSS garden. Both expose the same controller: update(plants),
// select(id, labelHtml), dispose(). The page works identically with either, or
// with none at all — the visual never carries information the cards lack.

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

// ----- CSS/2D garden -----------------------------------------------------------
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}[c]));

export function createFallbackGarden(container, {onSelect = () => {}, reducedMotion = false} = {}) {
  const root = document.createElement("div");
  root.className = "gd-garden2d" + (reducedMotion ? " is-still" : "");
  root.innerHTML = '<svg class="gd-hills" viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">'
    + '<path d="M0 170 C 180 120 320 150 480 130 S 800 110 1000 140 L1000 300 L0 300Z" class="gd-hill-back"/>'
    + '<path d="M0 215 C 200 185 360 205 540 190 S 830 180 1000 200 L1000 300 L0 300Z" class="gd-hill-front"/></svg>'
    + '<div class="gd-bed" role="list" aria-label="Setups in the garden"></div>';
  container.appendChild(root);
  const bed = root.querySelector(".gd-bed");
  let selectedId = null;
  const onClick = event => {
    const plant = event.target.closest("[data-plant-id]");
    if (plant) onSelect(plant.dataset.plantId);
  };
  bed.addEventListener("click", onClick);

  let signature = "";
  function update(plants) {
    const next = JSON.stringify(plants.map(p => [p.id, p.stage, p.direction, p.x.toFixed(2), p.z.toFixed(2)]));
    if (next === signature) return select(selectedId);   // unchanged: keep sway phases running
    signature = next;
    bed.innerHTML = plants.map(plant => {
      const depth = Math.max(0, Math.min(1, (4.0 - plant.z) / 9.4));   // 0 = front, 1 = back
      const left = ((plant.x + 8.5) / 17) * 90 + 5;
      const bottom = 7 + depth * 27;                                   // front hill .. back hill crest
      const scale = (1.15 - depth * 0.5).toFixed(2);
      return '<button type="button" role="listitem" class="gd-plant2d gd-p-' + plant.stage + ' gd-p-' + String(plant.direction || "none").toLowerCase()
        + (plant.id === selectedId ? ' is-selected' : '') + '" data-plant-id="' + esc(plant.id) + '" title="' + esc(plant.symbol) + '"'
        + ' style="left:' + left.toFixed(1) + '%;bottom:' + bottom.toFixed(1) + '%;--s:' + scale + ';--d:' + (plant.phase % 3).toFixed(2) + 's;z-index:' + Math.round((1 - depth) * 100) + '">'
        + '<span class="gd-p-stem"></span><span class="gd-p-leaf gd-p-leaf-l"></span><span class="gd-p-leaf gd-p-leaf-r"></span><span class="gd-p-head"></span>'
        + '<span class="gd-p-label">' + esc(plant.symbol) + '</span></button>';
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
