// TRADeden Garden — WebGL scene (Three.js). Loaded lazily by gardenMount.mjs, so the
// Three.js chunk is only downloaded when a WebGL garden is actually shown.
//
// Budget: one small terrain mesh, <=58 plants built from shared geometries and
// materials, 90 CPU-animated particles, no shadows, pixel ratio <=1.5, ~30 fps
// cap, rendering paused while the tab is hidden or the canvas is off-screen.
// With reduced motion the scene renders single static frames on change only.
import * as THREE from "three";

const COLORS = {
  stem: 0x5f8f6b, leaf: 0x7fb08a, leafDeep: 0x4f8a60, leafYoung: 0xa8cfa4,
  longPetal: 0x8fd6a8, shortPetal: 0xf29a9a, bloomCore: 0xf2c46b,
  longCrown: 0x3f9d63, shortCrown: 0xc85d5d, trunk: 0x8a6f55,
  history: 0xb9b3a6, historyLeaf: 0xcdb892,
  terrain: 0xd9e6d2, bed: 0xc9dcc1, particle: 0x86b394, ring: 0x1f2937,
};

const PLANT_SCALE = 1.35;

function terrainHeight(x, z) {
  return 0.32 * Math.sin(x * 0.42) * Math.cos(z * 0.55) + 0.16 * Math.sin(x * 0.9 + z * 0.35) - 0.05 * z;
}

export function createGardenScene(container, {reducedMotion = false, onSelect = () => {}} = {}) {
  const renderer = new THREE.WebGLRenderer({antialias: (window.devicePixelRatio || 1) < 2, alpha: true, powerPreference: "low-power"});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.className = "gd-canvas";
  renderer.domElement.setAttribute("aria-hidden", "true");
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xeef4ec, 24, 42);
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 60);
  const cameraBase = new THREE.Vector3(0, 6.2, 11.2);
  const lookTarget = new THREE.Vector3(0, 0.5, -0.6);
  const lookGoal = lookTarget.clone();
  camera.position.copy(cameraBase);

  scene.add(new THREE.HemisphereLight(0xffffff, 0xd8e3d4, 1.9));
  const sun = new THREE.DirectionalLight(0xfff6e8, 1.4);
  sun.position.set(6, 11, 7);
  scene.add(sun);

  const disposables = [];
  const keep = thing => (disposables.push(thing), thing);

  // Terrain
  const terrainGeometry = keep(new THREE.PlaneGeometry(26, 15, 52, 30));
  terrainGeometry.rotateX(-Math.PI / 2);
  const position = terrainGeometry.attributes.position;
  for (let i = 0; i < position.count; i++) position.setY(i, terrainHeight(position.getX(i), position.getZ(i)));
  terrainGeometry.computeVertexNormals();
  scene.add(new THREE.Mesh(terrainGeometry, keep(new THREE.MeshStandardMaterial({color: COLORS.terrain, roughness: 1, flatShading: true}))));
  // Three soft garden beds: history (back), growing (middle), bloom (front).
  const bedMaterial = keep(new THREE.MeshBasicMaterial({color: COLORS.bed, transparent: true, opacity: 0.55, depthWrite: false}));
  for (const [z, w] of [[-3.9, 9.5], [-0.3, 8.5], [2.9, 6.5]]) {
    const bed = new THREE.Mesh(keep(new THREE.CircleGeometry(1, 40)), bedMaterial);
    bed.rotation.x = -Math.PI / 2;
    bed.scale.set(w, 1.5, 1);
    bed.position.set(0, terrainHeight(0, z) + 0.03, z);
    scene.add(bed);
  }

  // Shared plant parts
  const geo = {
    stem: keep(new THREE.CylinderGeometry(0.035, 0.055, 1, 6)),
    leaf: keep(new THREE.SphereGeometry(0.5, 8, 6)),
    petal: keep(new THREE.SphereGeometry(0.5, 8, 6)),
    core: keep(new THREE.IcosahedronGeometry(0.11, 1)),
    crown: keep(new THREE.IcosahedronGeometry(0.62, 0)),
    trunk: keep(new THREE.CylinderGeometry(0.07, 0.11, 1, 6)),
    stump: keep(new THREE.CylinderGeometry(0.05, 0.07, 1, 5)),
    ring: keep(new THREE.RingGeometry(0.46, 0.54, 40)),
  };
  const materials = new Map();
  const mat = (color, options = {}) => {
    const key = color + JSON.stringify(options);
    if (!materials.has(key)) materials.set(key, keep(new THREE.MeshStandardMaterial({color, roughness: 0.85, flatShading: true, ...options})));
    return materials.get(key);
  };

  function leaf(group, y, angle, size, color) {
    const mesh = new THREE.Mesh(geo.leaf, mat(color));
    mesh.scale.set(0.2 * size, 0.045 * size, 0.42 * size);
    mesh.position.set(Math.cos(angle) * 0.17 * size, y, Math.sin(angle) * 0.17 * size);
    mesh.rotation.set(0.35, -angle + Math.PI / 2, 0);
    group.add(mesh);
  }

  function buildPlant(plant) {
    const group = new THREE.Group();
    const vigor = 0.8 + (Number(plant.score) || 50) / 250;
    const petalColor = plant.direction === "SHORT" ? COLORS.shortPetal : COLORS.longPetal;
    const crownColor = plant.direction === "SHORT" ? COLORS.shortCrown : COLORS.longCrown;
    let top = 0.6;
    if (plant.stage === "history") {
      const stump = new THREE.Mesh(geo.stump, mat(COLORS.history, {transparent: true, opacity: 0.75}));
      stump.scale.y = 0.42; stump.position.y = 0.21; group.add(stump);
      const fallen = new THREE.Mesh(geo.leaf, mat(COLORS.historyLeaf, {transparent: true, opacity: 0.8}));
      fallen.scale.set(0.2, 0.03, 0.36); fallen.position.set(0.22, 0.04, 0.1); fallen.rotation.y = plant.phase; group.add(fallen);
      top = 0.45;
    } else if (plant.stage === "active") {
      const height = 0.8 * vigor;
      const trunk = new THREE.Mesh(geo.trunk, mat(COLORS.trunk));
      trunk.scale.y = height; trunk.position.y = height / 2; group.add(trunk);
      const crown = new THREE.Mesh(geo.crown, mat(crownColor));
      crown.position.y = height + 0.28; crown.scale.setScalar(0.62 * vigor); group.add(crown);
      top = height + 0.75;
    } else {
      const height = (plant.stage === "growing" ? 0.55 : plant.stage === "shaping" ? 0.95 : 1.25) * vigor;
      const stem = new THREE.Mesh(geo.stem, mat(COLORS.stem));
      stem.scale.y = height; stem.position.y = height / 2; group.add(stem);
      const pairs = plant.stage === "growing" ? 1 : 2;
      for (let i = 0; i < pairs; i++) {
        const y = height * (0.45 + i * 0.28);
        const size = plant.stage === "growing" ? 0.75 : 1;
        const color = plant.stage === "growing" ? COLORS.leafYoung : i ? COLORS.leaf : COLORS.leafDeep;
        leaf(group, y, plant.phase + i * 1.3, size, color);
        leaf(group, y + 0.04, plant.phase + i * 1.3 + Math.PI, size, color);
      }
      if (plant.stage === "shaping") {
        const bud = new THREE.Mesh(geo.core, mat(petalColor));
        bud.position.y = height + 0.06; bud.scale.set(0.9, 1.3, 0.9); group.add(bud);
      }
      if (plant.stage === "bloomed") {
        const bloom = new THREE.Group();
        bloom.position.y = height + 0.05;
        for (let p = 0; p < 6; p++) {
          const angle = (p / 6) * Math.PI * 2;
          const petal = new THREE.Mesh(geo.petal, mat(petalColor));
          petal.scale.set(0.3, 0.07, 0.19);
          petal.position.set(Math.cos(angle) * 0.24, 0, Math.sin(angle) * 0.24);
          petal.rotation.y = -angle;
          bloom.add(petal);
        }
        const core = new THREE.Mesh(geo.core, mat(COLORS.bloomCore));
        core.scale.setScalar(1.3);
        bloom.add(core);
        bloom.rotation.x = 0.85;   // tilt the flower face toward the camera
        group.add(bloom);
        group.userData.bloom = bloom;
      }
      top = height + 0.35;
    }
    group.position.set(plant.x, terrainHeight(plant.x, plant.z), plant.z);
    group.scale.setScalar(PLANT_SCALE);
    group.userData = {...group.userData, id: plant.id, stage: plant.stage, phase: plant.phase, top, bornAt: null};
    return group;
  }

  // Particles
  const PARTICLES = 90;
  const particleGeometry = keep(new THREE.BufferGeometry());
  const particlePositions = new Float32Array(PARTICLES * 3);
  const particleSeeds = new Float32Array(PARTICLES);
  for (let i = 0; i < PARTICLES; i++) {
    particlePositions[i * 3] = (Math.random() - 0.5) * 20;
    particlePositions[i * 3 + 1] = Math.random() * 4;
    particlePositions[i * 3 + 2] = (Math.random() - 0.5) * 11;
    particleSeeds[i] = Math.random() * Math.PI * 2;
  }
  particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
  const particles = new THREE.Points(particleGeometry, keep(new THREE.PointsMaterial({color: COLORS.particle, size: 0.07, transparent: true, opacity: 0.55, depthWrite: false})));
  scene.add(particles);

  // Selection ring
  const ringMaterial = keep(new THREE.MeshBasicMaterial({color: COLORS.ring, transparent: true, opacity: 0.4, depthWrite: false, side: THREE.DoubleSide}));
  const ring = new THREE.Mesh(geo.ring, ringMaterial);
  ring.rotation.x = -Math.PI / 2;
  ring.visible = false;
  scene.add(ring);

  const plants = new Map();          // id -> {group, key}
  let selectedId = null;
  let firstUpdate = true;
  const pin = document.createElement("div");
  pin.className = "gd-pin";
  pin.hidden = true;
  container.appendChild(pin);

  // ----- loop --------------------------------------------------------------
  let frame = 0, lastRender = 0, visible = true, disposed = false;
  const pointer = {x: 0, y: 0};
  const clock = new THREE.Clock();
  const animate = !reducedMotion;

  function resize() {
    const width = container.clientWidth || 1, height = container.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.fov = width < 700 ? 42 : 34;
    camera.updateProjectionMatrix();
    requestRender();
  }

  function placePin() {
    const entry = selectedId && plants.get(selectedId);
    if (!entry) { pin.hidden = true; return; }
    const point = entry.group.position.clone();
    point.y += entry.group.userData.top * entry.group.scale.y + 0.15;
    point.project(camera);
    const x = (point.x * 0.5 + 0.5) * container.clientWidth, y = (-point.y * 0.5 + 0.5) * container.clientHeight;
    pin.hidden = false;
    pin.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px) translate(-50%,-100%)";
  }

  function draw(time) {
    const t = clock.getElapsedTime();
    if (animate) {
      for (const {group} of plants.values()) {
        const data = group.userData;
        if (data.stage !== "history") {
          group.rotation.z = Math.sin(t * 0.8 + data.phase) * 0.035;
          group.rotation.x = Math.cos(t * 0.6 + data.phase) * 0.02;
        }
        if (data.bornAt != null) {
          const k = Math.min(1, (time - data.bornAt) / 1400);
          const ease = 1 - Math.pow(1 - k, 3);
          const base = group.userData.baseScale || 1;
          group.scale.setScalar(base * (0.25 + 0.75 * ease));
          if (data.bloom) data.bloom.rotation.y = (1 - ease) * 1.2;
          if (k >= 1) data.bornAt = null;
        }
      }
      for (let i = 0; i < PARTICLES; i++) {
        let y = particlePositions[i * 3 + 1] + 0.004;
        if (y > 4) y = 0;
        particlePositions[i * 3 + 1] = y;
        particlePositions[i * 3] += Math.sin(t * 0.5 + particleSeeds[i]) * 0.003;
      }
      particleGeometry.attributes.position.needsUpdate = true;
      camera.position.x += (cameraBase.x + pointer.x * 0.7 - camera.position.x) * 0.04;
      camera.position.y += (cameraBase.y - pointer.y * 0.35 - camera.position.y) * 0.04;
      lookTarget.lerp(lookGoal, 0.05);
      if (ring.visible) ringMaterial.opacity = 0.32 + Math.sin(t * 2.2) * 0.08;
    } else {
      lookTarget.copy(lookGoal);
    }
    camera.lookAt(lookTarget);
    renderer.render(scene, camera);
    placePin();
  }

  function loop(time) {
    frame = 0;
    if (disposed || !visible || document.hidden) return;
    if (time - lastRender >= 33) { lastRender = time; draw(time); }
    frame = requestAnimationFrame(loop);
  }
  function requestRender() {
    if (disposed) return;
    if (animate) { if (!frame && visible && !document.hidden) frame = requestAnimationFrame(loop); }
    else if (!frame) frame = requestAnimationFrame(time => { frame = 0; draw(time); });
  }

  // ----- interaction ---------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function plantAt(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects([...plants.values()].map(entry => entry.group), true)[0];
    let node = hit?.object;
    while (node && !node.userData?.id) node = node.parent;
    return node?.userData?.id || null;
  }
  const onPointerMove = event => {
    const rect = container.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
    pointer.y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
    renderer.domElement.style.cursor = plantAt(event) ? "pointer" : "default";
  };
  const onClick = event => { const id = plantAt(event); if (id) onSelect(id); };
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
  function update(nextPlants) {
    const next = new Map(nextPlants.map(plant => [plant.id, plant]));
    for (const [id, entry] of plants) {
      if (!next.has(id)) { scene.remove(entry.group); plants.delete(id); }
    }
    for (const plant of nextPlants) {
      const key = plant.stage + "|" + plant.direction + "|" + Math.round((Number(plant.score) || 0) / 10);
      const existing = plants.get(plant.id);
      if (existing && existing.key === key) {
        existing.group.position.set(plant.x, terrainHeight(plant.x, plant.z), plant.z);
        continue;
      }
      if (existing) scene.remove(existing.group);
      const group = buildPlant(plant);
      const becameBloom = plant.stage === "bloomed" && existing?.stage !== "bloomed";
      group.userData.baseScale = PLANT_SCALE;
      if (!firstUpdate && animate && (becameBloom || !existing)) group.userData.bornAt = performance.now();
      scene.add(group);
      plants.set(plant.id, {group, key, stage: plant.stage});
    }
    firstUpdate = false;
    select(selectedId);
    requestRender();
  }

  function select(id, label = null) {
    selectedId = id && plants.has(id) ? id : null;
    const entry = selectedId && plants.get(selectedId);
    ring.visible = Boolean(entry);
    if (entry) {
      ring.position.set(entry.group.position.x, entry.group.position.y + 0.04, entry.group.position.z);
      ring.scale.setScalar(PLANT_SCALE);
      ringMaterial.color.set(entry.stage === "history" ? 0x9ca3af : COLORS.ring);
      lookGoal.set(entry.group.position.x * 0.35, 0.5, entry.group.position.z * 0.25 - 0.6);
      if (label != null) pin.innerHTML = label;
    } else {
      lookGoal.set(0, 0.5, -0.6);
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
    for (const item of disposables) item.dispose?.();
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
    pin.remove();
  }

  return {kind: "webgl", update, select, dispose};
}
