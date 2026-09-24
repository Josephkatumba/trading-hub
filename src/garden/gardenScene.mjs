// TRADeden Garden — the living market constellation (Three.js). Loaded lazily by
// gardenMount.mjs, so the Three.js chunk only downloads when the 3D garden shows.
//
// Every orb is a real setup, placed by lifecycle stage (see gardenModel BANDS):
// developing orbs are small and sage, confirming orbs gain an energy ring, a
// confirmed setup matures into a mint (long) or coral (short) orb with a soft
// bloom crown, active setups hold a stable field ring, and closed setups settle
// as quiet grey points on the outer archive ring. The environment — drifting
// dust, flowing currents, lifecycle rings and a slow scanning sweep — is
// ambient only and never represents data, so the garden stays alive without
// inventing anything.
//
// Budget: shared geometries/materials, <=64 orbs, GPU-animated dust and
// currents (no per-frame CPU loops over particles), no shadows, pixel ratio
// <=1.5, ~30 fps cap, paused while the tab is hidden or the canvas is off-screen,
// static frames under reduced motion, full dispose on navigation.
import * as THREE from "three";

const PALETTE = {
  growing: 0x8fbba0, shaping: 0x4fa37c, long: 0x2ebd82, short: 0xec6f63,
  confirmed: 0x8a7fc2, history: 0xa9b0ac, ink: 0x1c2321,
  dust: 0x8fae9c, current: 0x6fae8e, ring: 0x9fb3a6, sweep: 0x7fb896,
};
const ORB_SIZE = {growing: 0.14, shaping: 0.21, bloomed: 0.3, active: 0.34, history: 0.065};

const ORB_VERTEX = `
varying vec3 vNormal; varying vec3 vView;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vNormal = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;
// Translucent bubble on a light background: lighter core, tinted rim, soft highlight.
const ORB_FRAGMENT = `
uniform vec3 uColor; uniform float uOpacity; uniform float uLift;
varying vec3 vNormal; varying vec3 vView;
void main() {
  float facing = max(dot(vNormal, vView), 0.0);
  float rim = pow(1.0 - facing, 2.2);
  vec3 core = mix(uColor, vec3(1.0), 0.42 + uLift);
  vec3 color = mix(core, uColor * 0.86, rim);
  float spec = pow(max(dot(vNormal, normalize(vec3(-0.45, 0.65, 0.62))), 0.0), 28.0);
  color += spec * 0.5;
  gl_FragColor = vec4(color, uOpacity * (0.5 + 0.5 * rim));
}`;
const DUST_VERTEX = `
uniform float uTime; uniform float uPixel;
attribute float aSeed; attribute float aSize;
varying float vAlpha;
void main() {
  vec3 p = position;
  p.y += sin(uTime * (0.18 + aSeed * 0.22) + aSeed * 40.0) * 0.35;
  p.x += cos(uTime * 0.07 + aSeed * 17.0) * 0.4;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = min(aSize * uPixel * (9.0 / -mv.z), 5.0 * uPixel);
  vAlpha = 0.25 + 0.45 * fract(aSeed * 7.13);
  gl_Position = projectionMatrix * mv;
}`;
const DUST_FRAGMENT = `
uniform vec3 uColor; varying float vAlpha;
void main() {
  float d = length(gl_PointCoord - 0.5);
  if (d > 0.5) discard;
  gl_FragColor = vec4(uColor, vAlpha * smoothstep(0.5, 0.0, d));
}`;
const CURRENT_VERTEX = `
attribute float aU; varying float vU;
void main() { vU = aU; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const CURRENT_FRAGMENT = `
uniform vec3 uColor; uniform float uTime; uniform float uOffset; varying float vU;
void main() {
  float head = fract(uTime * 0.035 + uOffset);
  float pulse = smoothstep(0.16, 0.0, abs(vU - head));
  float edge = smoothstep(0.0, 0.08, vU) * smoothstep(1.0, 0.92, vU);
  gl_FragColor = vec4(uColor, (0.11 + 0.38 * pulse) * edge);
}`;
const SWEEP_FRAGMENT = `
uniform vec3 uColor; uniform float uAngle; varying vec2 vUv;
void main() {
  vec2 p = vUv - 0.5;
  float r = length(p) * 2.0;
  if (r > 1.0 || r < 0.12) discard;
  float a = atan(p.y, p.x);
  float diff = mod(uAngle - a + 6.28318, 6.28318);
  float trail = smoothstep(1.2, 0.0, diff) * smoothstep(0.0, 0.08, diff);
  gl_FragColor = vec4(uColor, trail * 0.075 * (1.0 - r * 0.6));
}`;

function haloTexture() {
  const size = 128, canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255,255,255,0.9)");
  gradient.addColorStop(0.35, "rgba(255,255,255,0.35)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function copyOverlaysStage(container) {
  const parent = container.parentElement;
  return Boolean(parent) && getComputedStyle(parent).position === "absolute";
}

function stageColor(orb) {
  if (orb.stage === "history") return orb.outcome === "target" ? 0x9fcbb2 : orb.outcome === "stop" ? 0xdca7a1 : PALETTE.history;
  if (orb.stage === "bloomed" || orb.stage === "active") {
    return orb.direction === "LONG" ? PALETTE.long : orb.direction === "SHORT" ? PALETTE.short : PALETTE.confirmed;
  }
  return PALETTE[orb.stage] || PALETTE.growing;
}

export function createGardenScene(container, {reducedMotion = false, onSelect = () => {}} = {}) {
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
  const renderer = new THREE.WebGLRenderer({antialias: pixelRatio < 1.5, alpha: true, powerPreference: "low-power"});
  renderer.setPixelRatio(pixelRatio);
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.className = "gd-canvas";
  renderer.domElement.setAttribute("aria-hidden", "true");
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 80);
  const cameraBase = new THREE.Vector3(0, 6.6, 10.2);
  const lookTarget = new THREE.Vector3(0, 0.55, 0);
  const lookGoal = lookTarget.clone();
  camera.position.copy(cameraBase);

  const disposables = [];
  const keep = thing => (disposables.push(thing), thing);
  const time = {value: 0};
  const animate = !reducedMotion;

  // ----- ambient environment (not data) -----------------------------------
  const world = new THREE.Group();
  scene.add(world);

  // Faint lifecycle rings: bloom (inner), growing (middle), archive (outer).
  const ringLine = (radius, opacity) => {
    const points = [];
    for (let i = 0; i <= 128; i++) {
      const a = (i / 128) * Math.PI * 2;
      points.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
    }
    const line = new THREE.Line(keep(new THREE.BufferGeometry().setFromPoints(points)),
      keep(new THREE.LineBasicMaterial({color: PALETTE.ring, transparent: true, opacity, depthWrite: false})));
    world.add(line);
  };
  ringLine(2.45, 0.28); ringLine(4.95, 0.2); ringLine(5.7, 0.14);

  // Slow scanning sweep: TRADeden is always watching.
  const sweepUniforms = {uColor: {value: new THREE.Color(PALETTE.sweep)}, uAngle: {value: 0}};
  const sweep = new THREE.Mesh(keep(new THREE.PlaneGeometry(12.6, 12.6)), keep(new THREE.ShaderMaterial({
    vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
    fragmentShader: SWEEP_FRAGMENT, uniforms: sweepUniforms, transparent: true, depthWrite: false,
  })));
  sweep.rotation.x = -Math.PI / 2;
  sweep.position.y = -0.01;
  world.add(sweep);

  // Drifting dust, animated on the GPU.
  const DUST = 380;
  const dustGeometry = keep(new THREE.BufferGeometry());
  const dustPositions = new Float32Array(DUST * 3), dustSeeds = new Float32Array(DUST), dustSizes = new Float32Array(DUST);
  let seed = 7;
  const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
  for (let i = 0; i < DUST; i++) {
    const a = random() * Math.PI * 2, r = Math.sqrt(random()) * 9;
    dustPositions.set([Math.cos(a) * r, random() * 3.8 - 0.3, Math.sin(a) * r * 0.8], i * 3);
    dustSeeds[i] = random();
    dustSizes[i] = 1.2 + random() * 2.6;
  }
  dustGeometry.setAttribute("position", new THREE.BufferAttribute(dustPositions, 3));
  dustGeometry.setAttribute("aSeed", new THREE.BufferAttribute(dustSeeds, 1));
  dustGeometry.setAttribute("aSize", new THREE.BufferAttribute(dustSizes, 1));
  world.add(new THREE.Points(dustGeometry, keep(new THREE.ShaderMaterial({
    vertexShader: DUST_VERTEX, fragmentShader: DUST_FRAGMENT, transparent: true, depthWrite: false,
    uniforms: {uTime: time, uPixel: {value: pixelRatio}, uColor: {value: new THREE.Color(PALETTE.dust)}},
  }))));

  // Flowing market currents: gentle curves with a travelling highlight.
  for (let c = 0; c < 5; c++) {
    const points = [];
    for (let k = 0; k < 6; k++) {
      const t = k / 5, a = c * 1.3 + t * 2.4;
      const r = 3 + Math.sin(c * 2.1 + t * 3.1) * 2.4;
      points.push(new THREE.Vector3(Math.cos(a) * r * 1.3, 0.2 + Math.sin(t * Math.PI + c) * 0.9 + 0.5, Math.sin(a) * r * 0.9));
    }
    const curve = new THREE.CatmullRomCurve3(points).getPoints(140);
    const geometry = keep(new THREE.BufferGeometry().setFromPoints(curve));
    geometry.setAttribute("aU", new THREE.BufferAttribute(new Float32Array(curve.map((_, i) => i / (curve.length - 1))), 1));
    world.add(new THREE.Line(geometry, keep(new THREE.ShaderMaterial({
      vertexShader: CURRENT_VERTEX, fragmentShader: CURRENT_FRAGMENT, transparent: true, depthWrite: false,
      uniforms: {uTime: time, uOffset: {value: c * 0.21}, uColor: {value: new THREE.Color(PALETTE.current)}},
    }))));
  }

  // ----- setup orbs (data) ----------------------------------------------------
  const sphere = keep(new THREE.SphereGeometry(1, 40, 28));
  const torus = keep(new THREE.TorusGeometry(1, 0.012, 6, 96));
  const halo = keep(haloTexture());
  const orbMaterials = new Map();
  const orbMaterial = (color, opacity, lift = 0) => {
    const key = color + ":" + opacity + ":" + lift;
    if (!orbMaterials.has(key)) orbMaterials.set(key, keep(new THREE.ShaderMaterial({
      vertexShader: ORB_VERTEX, fragmentShader: ORB_FRAGMENT, transparent: true, depthWrite: false,
      uniforms: {uColor: {value: new THREE.Color(color)}, uOpacity: {value: opacity}, uLift: {value: lift}},
    })));
    return orbMaterials.get(key);
  };
  const lineMaterials = new Map();
  const lineMaterial = (color, opacity) => {
    const key = color + ":" + opacity;
    if (!lineMaterials.has(key)) lineMaterials.set(key, keep(new THREE.MeshBasicMaterial({color, transparent: true, opacity, depthWrite: false})));
    return lineMaterials.get(key);
  };
  const haloMaterials = new Map();
  const haloMaterial = (color, opacity) => {
    const key = color + ":" + opacity;
    if (!haloMaterials.has(key)) haloMaterials.set(key, keep(new THREE.SpriteMaterial({map: halo, color, transparent: true, opacity, depthWrite: false})));
    return haloMaterials.get(key);
  };

  function buildOrb(orb) {
    const group = new THREE.Group();
    const color = stageColor(orb);
    const size = ORB_SIZE[orb.stage] * (orb.stage === "history" ? 1 : 0.85 + (Number(orb.score) || 50) / 330);
    const body = new THREE.Mesh(sphere, orbMaterial(color, orb.stage === "history" ? 0.55 : 0.92,
      orb.stage === "growing" ? 0.12 : 0));
    body.scale.setScalar(size);
    group.add(body);
    const parts = {body, spin: []};
    if (orb.stage !== "history") {
      const glow = new THREE.Sprite(haloMaterial(color, orb.stage === "growing" ? 0.35 : 0.5));
      glow.scale.setScalar(size * (orb.stage === "bloomed" ? 5.6 : orb.stage === "active" ? 4.8 : 3.4));
      group.add(glow);
    }
    if (orb.stage === "shaping") {             // conditions coming together
      for (const [tilt, radius] of [[1.1, 1.65], [0.5, 2.05]]) {
        const ring = new THREE.Mesh(torus, lineMaterial(color, 0.55));
        ring.scale.setScalar(size * radius);
        ring.rotation.set(tilt, orb.phase, 0);
        group.add(ring);
        parts.spin.push(ring);
      }
    }
    if (orb.stage === "bloomed") {             // matured: a still, bloom-like crown
      for (let p = 0; p < 6; p++) {
        const a = (p / 6) * Math.PI * 2 + orb.phase;
        const petal = new THREE.Mesh(sphere, orbMaterial(color, 0.5, 0.2));
        petal.scale.setScalar(size * 0.34);
        petal.position.set(Math.cos(a) * size * 1.45, Math.sin(p * 2.1) * size * 0.18, Math.sin(a) * size * 1.45);
        group.add(petal);
      }
    }
    if (orb.stage === "active") {              // stable surrounding field
      for (const radius of [1.7, 2.3]) {
        const field = new THREE.Mesh(torus, lineMaterial(color, radius > 2 ? 0.25 : 0.45));
        field.scale.setScalar(size * radius);
        field.rotation.x = Math.PI / 2;
        group.add(field);
      }
    }
    group.position.set(orb.x, orb.y, orb.z);
    group.userData = {id: orb.id, stage: orb.stage, phase: orb.phase, baseY: orb.y, size, parts, emphasis: 1, bornAt: null};
    return group;
  }

  // Constellation links (faint): live orbs to their nearest live neighbour.
  let links = null;
  const linkMaterial = keep(new THREE.LineBasicMaterial({color: PALETTE.ring, transparent: true, opacity: 0.35, depthWrite: false}));
  function rebuildLinks(orbList) {
    if (links) { world.remove(links); links.geometry.dispose(); links = null; }
    const live = orbList.filter(orb => orb.stage !== "history");
    const segments = [];
    for (const a of live) {
      let best = null, bestDistance = Infinity;
      for (const b of live) {
        if (a === b) continue;
        const distance = Math.hypot(a.x - b.x, a.z - b.z);
        if (distance < bestDistance) { bestDistance = distance; best = b; }
      }
      if (best && bestDistance < 3.2) segments.push(a.x, a.y, a.z, best.x, best.y, best.z);
    }
    if (!segments.length) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(segments, 3));
    links = new THREE.LineSegments(geometry, linkMaterial);
    world.add(links);
  }

  // Selection ring (camera-facing) and one-shot bloom effects.
  const selectRing = new THREE.Mesh(keep(new THREE.RingGeometry(1, 1.07, 64)),
    keep(new THREE.MeshBasicMaterial({color: PALETTE.ink, transparent: true, opacity: 0.55, depthWrite: false, side: THREE.DoubleSide})));
  selectRing.visible = false;
  scene.add(selectRing);
  const effects = [];
  const BURST = 26;
  const burstDirections = [];
  for (let i = 0; i < BURST; i++) {
    const a = (i / BURST) * Math.PI * 2, e = (i % 5 - 2) * 0.25;
    burstDirections.push(new THREE.Vector3(Math.cos(a), e, Math.sin(a)).normalize());
  }

  function bloomEffect(group, color) {
    const ring = new THREE.Mesh(torus, new THREE.MeshBasicMaterial({color, transparent: true, opacity: 0.6, depthWrite: false}));
    ring.position.copy(group.position);
    ring.rotation.x = Math.PI / 2;
    const burstGeometry = new THREE.BufferGeometry();
    burstGeometry.setAttribute("position", new THREE.Float32BufferAttribute(new Array(BURST * 3).fill(0), 3));
    const burst = new THREE.Points(burstGeometry, new THREE.PointsMaterial({color, size: 0.07, transparent: true, opacity: 0.8, depthWrite: false}));
    burst.position.copy(group.position);
    world.add(ring, burst);
    effects.push({ring, burst, start: performance.now(), size: group.userData.size});
  }
  function stepEffects(now) {
    for (let i = effects.length - 1; i >= 0; i--) {
      const effect = effects[i], k = Math.min(1, (now - effect.start) / 1800), ease = 1 - Math.pow(1 - k, 3);
      effect.ring.scale.setScalar(effect.size * (1.2 + ease * 3.6));
      effect.ring.material.opacity = 0.6 * (1 - k);
      const positions = effect.burst.geometry.attributes.position;
      burstDirections.forEach((direction, index) => positions.setXYZ(index, direction.x * ease * 1.6, direction.y * ease * 1.6, direction.z * ease * 1.6));
      positions.needsUpdate = true;
      effect.burst.material.opacity = 0.8 * (1 - k);
      if (k >= 1) {
        world.remove(effect.ring, effect.burst);
        effect.ring.material.dispose(); effect.burst.material.dispose(); effect.burst.geometry.dispose();
        effects.splice(i, 1);
      }
    }
  }

  const orbs = new Map();       // id -> {group, key, stage}
  let selectedId = null;
  let firstUpdate = true;
  const pin = document.createElement("div");
  pin.className = "gd-pin";
  pin.hidden = true;
  container.appendChild(pin);

  // ----- loop ---------------------------------------------------------------
  let frame = 0, lastRender = 0, visible = true, disposed = false;
  const pointer = {x: 0, y: 0};
  const clock = new THREE.Clock();
  const scratch = new THREE.Vector3();

  function resize() {
    const width = container.clientWidth || 1, height = container.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.fov = width / height < 1.3 ? 52 : 36;
    camera.updateProjectionMatrix();
    // When the hero copy overlays the stage (desktop), let the constellation sit right.
    world.position.x = copyOverlaysStage(container) && width / height > 1.6 ? Math.min(3.4, (width / height - 1.6) * 3 + 1.6) : 0;
    requestRender();
  }

  function placePin() {
    const entry = selectedId && orbs.get(selectedId);
    if (!entry) { pin.hidden = true; return; }
    entry.group.getWorldPosition(scratch);
    scratch.y += entry.group.userData.size * entry.group.scale.y * 1.7 + 0.12;
    scratch.project(camera);
    if (scratch.z > 1) { pin.hidden = true; return; }
    const x = (scratch.x * 0.5 + 0.5) * container.clientWidth, y = (-scratch.y * 0.5 + 0.5) * container.clientHeight;
    pin.hidden = false;
    pin.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px) translate(-50%,-100%)";
  }

  function draw(now) {
    const t = clock.getElapsedTime();
    if (animate) {
      time.value = t;
      sweepUniforms.uAngle.value = (t * 0.28) % (Math.PI * 2);
      world.rotation.y = Math.sin(t * 0.045) * 0.16;
      for (const {group} of orbs.values()) {
        const data = group.userData;
        if (data.stage !== "history") group.position.y = data.baseY + Math.sin(t * 0.55 + data.phase) * 0.05;
        for (const ring of data.parts.spin) ring.rotation.z += 0.004;
        let scale = data.emphasis;
        if (data.bornAt != null) {
          const k = Math.min(1, (now - data.bornAt) / 1600);
          scale *= 0.35 + 0.65 * (1 - Math.pow(1 - k, 3));
          if (k >= 1) data.bornAt = null;
          group.scale.setScalar(scale);
        } else {
          group.scale.setScalar(group.scale.x + (scale - group.scale.x) * 0.12);
        }
      }
      stepEffects(now);
      camera.position.x += (cameraBase.x + pointer.x * 0.8 - camera.position.x) * 0.035;
      camera.position.y += (cameraBase.y - pointer.y * 0.4 - camera.position.y) * 0.035;
      lookTarget.lerp(lookGoal, 0.05);
    } else {
      for (const {group} of orbs.values()) group.scale.setScalar(group.userData.emphasis);
      lookTarget.copy(lookGoal);
    }
    camera.lookAt(lookTarget);
    const selected = selectedId && orbs.get(selectedId);
    if (selected) {
      selected.group.getWorldPosition(selectRing.position);
      selectRing.scale.setScalar(selected.group.userData.size * selected.group.scale.x * 1.9);
      selectRing.quaternion.copy(camera.quaternion);
    }
    renderer.render(scene, camera);
    placePin();
  }

  function loop(now) {
    frame = 0;
    if (disposed || !visible || document.hidden) return;
    if (now - lastRender >= 33) { lastRender = now; draw(now); }
    frame = requestAnimationFrame(loop);
  }
  function requestRender() {
    if (disposed) return;
    if (animate) { if (!frame && visible && !document.hidden) frame = requestAnimationFrame(loop); }
    else if (!frame) frame = requestAnimationFrame(now => { frame = 0; draw(now); });
  }

  // ----- interaction ----------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function orbAt(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const bodies = [...orbs.values()].map(entry => entry.group.userData.parts.body);
    const hit = raycaster.intersectObjects(bodies, false)[0];
    if (hit) return hit.object.parent.userData.id;
    // Generous touch/click target: nearest orb centre within ~28px on screen.
    let best = null, bestDistance = 28;
    for (const {group} of orbs.values()) {
      const p = group.getWorldPosition(scratch).project(camera);
      const distance = Math.hypot(((p.x - ndc.x) / 2) * rect.width, ((p.y - ndc.y) / 2) * rect.height);
      if (distance < bestDistance) { bestDistance = distance; best = group.userData.id; }
    }
    return best;
  }
  const onPointerMove = event => {
    const rect = container.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
    pointer.y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
    if (event.pointerType === "mouse") renderer.domElement.style.cursor = orbAt(event) ? "pointer" : "default";
  };
  const onClick = event => { const id = orbAt(event); if (id) onSelect(id); };
  renderer.domElement.addEventListener("pointermove", onPointerMove);
  renderer.domElement.addEventListener("click", onClick);
  const onVisibility = () => { if (!document.hidden) requestRender(); };
  document.addEventListener("visibilitychange", onVisibility);
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(container);
  const intersection = new IntersectionObserver(entries => {
    visible = entries.some(entry => entry.isIntersecting);
    if (visible) requestRender();
  });
  intersection.observe(container);
  resize();

  // ----- public API ------------------------------------------------------------
  function update(nextOrbs) {
    const next = new Map(nextOrbs.map(orb => [orb.id, orb]));
    for (const [id, entry] of orbs) {
      if (!next.has(id)) { world.remove(entry.group); orbs.delete(id); }
    }
    for (const orb of nextOrbs) {
      const key = orb.stage + "|" + orb.direction + "|" + Math.round((Number(orb.score) || 0) / 10);
      const existing = orbs.get(orb.id);
      if (existing && existing.key === key) {
        existing.group.position.set(orb.x, existing.group.position.y, orb.z);
        existing.group.userData.baseY = orb.y;
        continue;
      }
      if (existing) world.remove(existing.group);
      const group = buildOrb(orb);
      // A real transition into CONFIRMED observed while the garden is open: one
      // restrained bloom. Never on the first paint, never for replayed history.
      const bloomed = orb.stage === "bloomed" && existing?.stage !== "bloomed";
      if (!firstUpdate && animate && bloomed) {
        group.userData.bornAt = performance.now();
        group.scale.setScalar(0.35);
        bloomEffect(group, stageColor(orb));
      } else if (!firstUpdate && animate && !existing) {
        group.scale.setScalar(0.4);            // new orbs ease in
      }
      world.add(group);
      orbs.set(orb.id, {group, key, stage: orb.stage});
    }
    rebuildLinks(nextOrbs);
    firstUpdate = false;
    select(selectedId);
    requestRender();
  }

  function select(id, label = null) {
    selectedId = id && orbs.has(id) ? id : null;
    for (const [orbId, entry] of orbs) entry.group.userData.emphasis = orbId === selectedId ? 1.2 : 1;
    const entry = selectedId && orbs.get(selectedId);
    selectRing.visible = Boolean(entry);
    if (entry) {
      selectRing.material.color.set(entry.stage === "history" ? 0x8c948f : PALETTE.ink);
      lookGoal.set(entry.group.position.x * 0.25, 0.55, entry.group.position.z * 0.2);
      if (label != null) pin.innerHTML = label;
    } else {
      lookGoal.set(0, 0.55, 0);
      pin.hidden = true;
    }
    requestRender();
  }

  function dispose() {
    disposed = true;
    if (frame) cancelAnimationFrame(frame);
    resizeObserver.disconnect();
    intersection.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    renderer.domElement.removeEventListener("pointermove", onPointerMove);
    renderer.domElement.removeEventListener("click", onClick);
    for (const effect of effects) { effect.ring.material.dispose(); effect.burst.material.dispose(); effect.burst.geometry.dispose(); }
    if (links) links.geometry.dispose();
    for (const item of disposables) item.dispose?.();
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
    pin.remove();
  }

  return {kind: "webgl", update, select, dispose};
}
