// 3d-model-skill viewer: one static page, three.js, and a contract (controls.json) that the
// generator wrote. Nothing here knows about houses: it recolors materials by name,
// swaps GLBs into slots, and slides named nodes. Change the model, not this file.
import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {GLTFExporter} from './vendor/GLTFExporter.js';

const $ = id => document.getElementById(id);

// ---------------------------------------------------------------- scene
const scene = new THREE.Scene();
scene.background = new THREE.Color('#dfe6ea');
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.05, 400);
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
$('viewport').append(renderer.domElement);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const hemi = new THREE.HemisphereLight(0xffffff, 0xb9b1a3, 2.1);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xfff3e2, 2.4);
sun.position.set(-14, 24, 18);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, {left: -22, right: 22, top: 22, bottom: -22, near: 1, far: 120});
sun.shadow.camera.updateProjectionMatrix();   // without this it keeps the default 10 m box and the porch gets no shadows
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.02;
scene.add(sun, sun.target);
const fill = new THREE.DirectionalLight(0xffffff, 0.6);
fill.position.set(12, 8, -16);
scene.add(fill);
// A phone held upright sees a sliver at 50 degrees; widen the vertical field so a view
// frames about the same width on both.
function fit() {
  camera.aspect = innerWidth / innerHeight;
  camera.fov = camera.aspect < 1 ? 72 : 50;
  // On a desktop the panel covers the right 344px: center the picture in what's left.
  if (innerWidth > 720) camera.setViewOffset(innerWidth, innerHeight, 172, 0, innerWidth, innerHeight);
  else camera.clearViewOffset();
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}
addEventListener('resize', fit);
fit();

// Calmer swings than three's default (rotateSpeed 1): a phone swipe shouldn't spin the house.
const orbit = new OrbitControls(camera, renderer.domElement);
orbit.enableDamping = true;
orbit.dampingFactor = 0.1;
orbit.rotateSpeed = 0.45;
orbit.minDistance = 0.5;
orbit.maxDistance = 80;
orbit.maxPolarAngle = Math.PI * 0.495;

const loader = new GLTFLoader();
const cache = new Map();            // url -> Promise<gltf scene>
const slots = new Map();            // slot id -> {url, group}
const root = new THREE.Group();
scene.add(root);

// ---------------------------------------------------------------- the contract
let contract, settings = {}, fields = new Map(), views = [], selected = 0;

function fieldOptions(f) {
  // A color field can take its choices from another field: each door has its own colors.
  if (f.options_by) return f.options_by_value[settings[f.options_by]] || [];
  if (f.kind === 'steps') return f.values.map(v => [String(v)]);
  return f.options;
}
function optionKeys(f) {
  const o = fieldOptions(f);
  return Array.isArray(o) ? o.map(x => x[0]) : Object.keys(o);
}
function defaults() {
  const s = {};
  for (const f of fields.values()) s[f.id] = f.default ?? optionKeys(f)[0];
  return s;
}
function fix(s) {
  // Keep every value legal: a door color has to exist on the door you just picked.
  for (const f of fields.values()) {
    if (f.kind === 'range') s[f.id] = Math.min(f.max, Math.max(f.min, Number(s[f.id]) || 0));
    else if (f.kind === 'toggle') s[f.id] = s[f.id] === true || s[f.id] === '1' || s[f.id] === 'true';
    else if (!optionKeys(f).includes(s[f.id])) s[f.id] = f.default ?? optionKeys(f)[0];
  }
  return s;
}

// ---------------------------------------------------------------- parameters, 1: color
// Recolor by material name. The generator named every material for the paint it wears.
const brickTexture = makeBrickTexture();
function colorOf(f, key) {
  const o = fieldOptions(f).find(x => x[0] === key);
  return o ? o[2] : null;
}
function materialColors() {
  const out = {};
  for (const f of fields.values()) {
    if (f.kind !== 'color') continue;
    const hex = colorOf(f, settings[f.id]);
    if (hex) for (const m of f.materials) out[m] = hex;
  }
  // Natural brick ignores the body paint; painted brick takes it.
  const b = contract.brick;
  out['cladding.brick'] = settings[b.paint_toggle] ? out[fields.get(b.paint_field).materials[0]] : b.natural;
  return out;
}
function applyColors() {
  const colors = materialColors();
  root.traverse(o => {
    if (!o.isMesh) return;
    for (const m of [].concat(o.material)) {
      if (colors[m.name]) m.color.set(colors[m.name]);
      if (m.name === 'glass') { m.transparent = true; m.opacity = 0.35; m.depthWrite = false; }
      if (m.name === 'cladding.brick' && !m.map) { m.map = brickTexture; m.needsUpdate = true; brickUV(o.geometry); }
    }
  });
}

// A brick texture without UVs in the model: project world position onto the face's plane.
function makeBrickTexture() {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#f4f2ee'; g.fillRect(0, 0, 256, 128);             // mortar, lighter than brick
  for (let row = 0; row < 4; row++) for (let i = -1; i < 3; i++) {
    const x = i * 128 + (row % 2) * 64, shade = 196 + ((row * 7 + i * 13) % 5) * 7;
    g.fillStyle = `rgb(${shade},${shade},${shade})`;
    g.fillRect(x + 4, row * 32 + 4, 120, 26);
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();   // no shimmer at grazing angles
  return t;
}
function brickUV(geometry) {
  // One tile = 2 bricks (8" each) across, 4 courses (2 2/3" each) up.
  const W = 16 * 0.0254, H = 4 * (8 / 3) * 0.0254;
  if (!geometry.attributes.normal) geometry.computeVertexNormals();
  const p = geometry.attributes.position, n = geometry.attributes.normal, uv = new Float32Array(p.count * 2);
  for (let i = 0; i < p.count; i++) {
    const nx = Math.abs(n.getX(i)), ny = Math.abs(n.getY(i));
    const u = nx > 0.5 ? p.getZ(i) : p.getX(i), v = ny > 0.5 ? p.getZ(i) : p.getY(i);
    uv[i * 2] = u / W; uv[i * 2 + 1] = v / H;
  }
  geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
}

// ---------------------------------------------------------------- light, sun and site
// Not parameters of the house, so they aren't in the contract's sections: how you look at it.
// Day puts the sun where it really is (lat/long, the model's bearing, month and hour);
// dusk turns on the contract's lights and lights the windows from inside.
const DISPLAY_DEFAULTS = {light: 'day', hour: 10, month: 6,   // 10 a.m.: this example faces ESE, so the front is in sun
  exposure: 0, scan: false, ghost: false, lot: true};
const display = {...DISPLAY_DEFAULTS};
const LIGHTS = {
  day: {sky: '#dfe6ea', hemi: 2.1, sun: 2.4, fill: 0.6, glow: 0, lamps: 0, shadows: true},
  overcast: {sky: '#d5d9dc', hemi: 2.9, sun: 0.5, fill: 0.9, glow: 0, lamps: 0, shadows: false},
  dusk: {sky: '#27304a', hemi: 0.45, sun: 0.35, fill: 0.08, glow: 0.9, lamps: 1, shadows: false},
};
const lamps = new THREE.Group();
scene.add(lamps);
// Solar position, good to a degree or so: declination from the day of year, hour angle from
// solar time (the hour slider is solar time, not the clock: no time zones here).
function sunDirection(lat, month, hour) {
  const rad = Math.PI / 180, day = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349][month - 1];
  const dec = 23.44 * Math.sin(rad * 360 / 365 * (day - 81)) * rad, H = 15 * (hour - 12) * rad, phi = lat * rad;
  const el = Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H));
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(dec) * Math.cos(phi)) + Math.PI;  // from north, clockwise
  return {el, az};
}
// Compass bearing -> viewer direction. Model +Y has bearing y_bearing and +X is 90 degrees
// clockwise from it; the viewer is glTF Y-up, so model (x, y, z) is (x, z, -y).
function bearingToWeb(az, el) {
  const d = az - contract.site.y_bearing * Math.PI / 180;
  return new THREE.Vector3(Math.sin(d) * Math.cos(el), Math.sin(el), -Math.cos(d) * Math.cos(el));
}
function applyLight() {
  const L = LIGHTS[display.light], k = 2 ** display.exposure;
  scene.background.set(L.sky);
  hemi.intensity = L.hemi * k; fill.intensity = L.fill * k;
  const center = new THREE.Vector3(2.4, 0, -6);
  let dir;
  if (display.light === 'day') {
    const {el, az} = sunDirection(contract.site.anchor.lat, display.month, display.hour);
    dir = bearingToWeb(az, Math.max(el, 0.02));
    sun.intensity = (el > 0 ? L.sun * Math.min(1, el / 0.25 + 0.3) : 0.05) * k;
    sun.color.set(el < 0.2 ? '#ffd2a0' : '#fff3e2');
  } else {
    dir = display.light === 'dusk' ? bearingToWeb(contract.site.y_bearing * Math.PI / 180 + 2, 0.05) : new THREE.Vector3(-0.4, 1, 0.5).normalize();
    sun.intensity = L.sun * k;
    sun.color.set(display.light === 'dusk' ? '#ff9a6a' : '#ffffff');
  }
  sun.position.copy(center).addScaledVector(dir, 50);
  sun.target.position.copy(center);
  sun.castShadow = L.shadows;
  lamps.visible = L.lamps > 0;
  for (const l of lamps.children) l.intensity = l.userData.power * L.lamps * k;
  root.traverse(o => {
    if (!o.isMesh) return;
    const m = o.material;
    if (m.name === 'glass') { m.emissive?.set('#ffcf8a'); m.emissiveIntensity = L.glow; }
  });
  updateCompass();
}
function buildLamps() {
  for (const l of contract.lights || []) {
    const p = new THREE.PointLight(l.color, 0, 9, 2);
    p.position.set(...l.at);
    p.userData.power = l.power * 0.06;
    lamps.add(p);
  }
}
// The lot, dashed on the ground, and a compass that turns with the camera.
let lotLine = null;
function buildLot() {
  const g = contract.site.ground + 0.03, pts = contract.site.lot.map(([x, z]) => new THREE.Vector3(x, g, z));
  lotLine = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({color: '#c4561a', dashSize: 0.35, gapSize: 0.2}));
  lotLine.computeLineDistances();
  scene.add(lotLine);
}
function updateCompass() {
  if (!contract) return;
  const f = new THREE.Vector3();
  camera.getWorldDirection(f);
  // viewer (x, -z) is model (x, y); bearing of the view = y_bearing + angle of the view from +Y
  const heading = contract.site.y_bearing + Math.atan2(f.x, -f.z) * 180 / Math.PI;
  $('compass').style.setProperty('--north', `${-heading}deg`);
}
// The evidence layer: the registered scan as points, and the model ghosted to see through it.
let scanPoints = null;
async function applyEvidence() {
  if (display.scan && !scanPoints && contract.scan) {
    const g = await load(contract.scan.url);
    scanPoints = g.clone(true);
    scanPoints.traverse(o => { if (o.isPoints) o.material = new THREE.PointsMaterial({size: 0.025, vertexColors: true, sizeAttenuation: true}); });
    scene.add(scanPoints);
  }
  if (scanPoints) scanPoints.visible = display.scan;
  root.traverse(o => {
    if (!o.isMesh || o.material.name === 'glass') return;
    // transparent is baked into the shader (three compiles an opaque variant), so changing it needs a recompile
    if (o.material.transparent !== display.ghost) o.material.needsUpdate = true;
    o.material.transparent = display.ghost;
    o.material.opacity = display.ghost ? 0.08 : 1;   // walls are several stacked faces, so keep each one faint
    o.material.depthWrite = !display.ghost;
  });
  if (lotLine) lotLine.visible = display.lot;
  refreshDetails();   // the scan layer and the slots change what's on screen
}

// ---------------------------------------------------------------- existing and proposed
// Existing is the house as measured (the contract's `existing`), shown over the proposed
// settings without touching them. The panel locks; switch back and your design is there.
let state = 'proposed', proposedSettings = null;
const proposed = () => state === 'existing' ? proposedSettings : settings;
async function setState(st) {
  if (st === state) return;
  if (st === 'existing') { proposedSettings = {...settings}; settings = fix({...settings, ...contract.existing}); }
  else { settings = proposedSettings; proposedSettings = null; }
  state = st;
  document.body.dataset.state = st;
  buildPanel();
  syncURL();
  await applySlots();
}

// ---------------------------------------------------------------- parameters, 2: swap
// A slot's file name is a template over the settings. rear-{door}-{cladding}.glb reloads
// when either changes; everything else stays put.
function load(url) {
  if (!cache.has(url)) cache.set(url, loader.loadAsync(url).then(g => g.scene));
  return cache.get(url);
}
async function applySlots() {
  const jobs = Object.entries(contract.slots).map(async ([id, template]) => {
    const url = template.replace(/\{(\w+)\}/g, (_, k) => settings[k]);
    const slot = slots.get(id);
    if (slot?.url === url) return;
    const model = await load(url);
    const now = slots.get(id);
    if (now && now.url !== slot?.url) return;           // a newer choice won the race
    if (now) root.remove(now.group);
    const group = model.clone(true);                     // clone: materials stay per-instance
    group.traverse(o => { if (o.isMesh) { o.material = [].concat(o.material).map(m => m.clone())[0]; o.castShadow = o.receiveShadow = true; } });
    group.userData.slot = id;                            // a comment pin says which slot it hit
    root.add(group);
    slots.set(id, {url, group});
  });
  await Promise.all(jobs);
  applyColors();
  applyRanges();
  applyClip();
  applyLight();
  applyEvidence();
}

// ---------------------------------------------------------------- parameters, 3: range
// Slide a named node. How far is the generator's business (it read the spec sheet).
function applyRanges() {
  for (const f of fields.values()) {
    if (f.kind !== 'range') continue;
    const [by, table] = Object.entries(f.travel_by)[0];
    const travel = table[settings[by]] || 0;
    root.traverse(o => {
      // GLTFLoader strips dots from o.name (door.operable -> dooroperable); the original is in userData.name.
      if (!(o.userData.name || '').startsWith(f.node)) return;
      o.userData.home ??= o.position.clone();
      o.position.x = o.userData.home.x - travel * settings[f.id] / 100;
    });
  }
}

// ---------------------------------------------------------------- the panel
function swatch(f, [key, name, hex]) {
  const b = document.createElement('button');
  b.className = 'chip';
  b.style.setProperty('--chip', hex);
  b.title = name;
  b.setAttribute('aria-label', name);
  b.setAttribute('aria-pressed', settings[f.id] === key);
  b.onclick = () => set(f.id, key);
  return b;
}
function buildPanel() {
  const body = $('panel-body');
  body.replaceChildren();
  const st = document.createElement('div');
  st.className = 'state seg';
  for (const [k, label] of [['existing', 'Existing'], ['proposed', 'Proposed']]) {
    const b = document.createElement('button');
    b.textContent = label;
    b.setAttribute('aria-pressed', state === k);
    b.onclick = () => setState(k);
    st.append(b);
  }
  body.append(st);
  if (state === 'existing') {
    const n = document.createElement('p');
    n.className = 'note';
    n.textContent = 'The house as measured. Switch to Proposed to change things; your design is kept.';
    body.append(n);
  }
  const sections = document.createElement('div');
  sections.className = state === 'existing' ? 'locked' : '';
  body.append(sections);
  for (const s of contract.sections) {
    const fs = document.createElement('fieldset');
    const lg = document.createElement('legend');
    lg.textContent = s.name;
    fs.append(lg);
    // Drawings for exactly what's on screen: the template picks the set for these settings.
    const sheet = s.drawings?.replace(/\{(\w+)\}/g, (_, k) => settings[k]);
    if (sheet && !sheet.includes('-none')) {
      const a = Object.assign(document.createElement('a'), {href: sheet, className: 'drawings', textContent: 'Construction drawings ↗'});
      a.target = '_blank';
      fs.append(a);
    }
    for (const raw of s.fields) {
      const f = fields.get(raw.id);
      if (f.when && Object.entries(f.when).some(([k, v]) => settings[k] !== v)) continue;
      if (f.id.startsWith('door_') && settings.door === 'none') continue;
      const row = document.createElement('div');
      row.className = 'row';
      const label = document.createElement('label');
      label.className = 'label';
      row.append(label);
      if (f.kind === 'color') {
        const opts = fieldOptions(f);
        const current = opts.find(o => o[0] === settings[f.id]);
        label.innerHTML = `${f.label} <span>${current ? current[1] : ''}</span>`;
        const chips = document.createElement('div');
        chips.className = 'chips';
        for (const o of opts) chips.append(swatch(f, o));
        row.append(chips);
      } else if (f.kind === 'swap') {
        label.textContent = f.label;
        const seg = document.createElement('div');
        seg.className = 'seg';
        for (const [key, o] of Object.entries(f.options)) {
          const b = document.createElement('button');
          b.textContent = o.label;
          b.setAttribute('aria-pressed', settings[f.id] === key);
          b.onclick = () => set(f.id, key);
          seg.append(b);
        }
        row.append(seg);
        row.append(note(f));
      } else if (f.kind === 'steps') {
        // A slider over pre-built shapes: each stop is its own GLB (and its own drawing set).
        const vals = f.values.map(String), i = vals.indexOf(settings[f.id]);
        label.innerHTML = `${f.label} <span>${settings[f.id]}${f.unit || ''}</span>`;
        const input = document.createElement('input');
        Object.assign(input, {type: 'range', min: 0, max: vals.length - 1, step: 1, value: i});
        input.setAttribute('aria-label', f.label);
        input.setAttribute('list', f.id + '-ticks');
        input.oninput = () => { label.querySelector('span').textContent = vals[input.value] + (f.unit || ''); };
        input.onchange = () => set(f.id, vals[input.value]);
        const ticks = document.createElement('datalist');
        ticks.id = f.id + '-ticks';
        for (const [k] of vals.entries()) ticks.append(new Option('', k));
        row.append(input, ticks);
        if (f.note) { const n = document.createElement('div'); n.className = 'note'; n.textContent = f.note; row.append(n); }
      } else if (f.kind === 'toggle') {
        label.innerHTML = `<input type="checkbox" ${settings[f.id] ? 'checked' : ''}> ${f.label}`;
        label.querySelector('input').onchange = e => set(f.id, e.target.checked);
      } else if (f.kind === 'range') {
        label.innerHTML = `${f.label} <span>${Math.round(settings[f.id])}${f.unit || ''}</span>`;
        const input = document.createElement('input');
        Object.assign(input, {type: 'range', min: f.min, max: f.max, step: 1, value: settings[f.id]});
        input.setAttribute('aria-label', f.label);
        input.oninput = () => { settings[f.id] = Number(input.value); label.querySelector('span').textContent = input.value + (f.unit || ''); applyRanges(); syncURL(); };
        row.append(input);
      }
      fs.append(row);
    }
    sections.append(fs);
  }
  body.append(...extraSections());
}

// Light, evidence and files: how you look at the house, not what it is.
function extraSections() {
  const out = [];
  const section = name => { const fs = document.createElement('fieldset'); const lg = document.createElement('legend'); lg.textContent = name; fs.append(lg); out.push(fs); return fs; };
  const row = (fs, label) => { const r = document.createElement('div'); r.className = 'row'; const l = document.createElement('label'); l.className = 'label'; l.innerHTML = label; r.append(l); fs.append(r); return r; };
  const slider = (fs, label, key, min, max, step, show, after) => {
    const r = row(fs, `${label} <span>${show(display[key])}</span>`), input = document.createElement('input');
    Object.assign(input, {type: 'range', min, max, step, value: display[key]});
    input.setAttribute('aria-label', label);
    input.oninput = () => { display[key] = Number(input.value); r.querySelector('span').textContent = show(display[key]); (after || applyLight)(); syncURL(); };
    r.append(input);
  };
  const check = (fs, label, key, after) => {
    const r = row(fs, `<input type="checkbox" ${display[key] ? 'checked' : ''}> ${label}`);
    r.querySelector('input').onchange = e => { display[key] = e.target.checked; after(); syncURL(); };
    return r;
  };

  const light = section('Light');
  const seg = document.createElement('div');
  seg.className = 'seg';
  for (const k of Object.keys(LIGHTS)) {
    const b = document.createElement('button');
    b.textContent = k[0].toUpperCase() + k.slice(1);
    b.setAttribute('aria-pressed', display.light === k);
    b.onclick = () => { display.light = k; applyLight(); buildPanel(); syncURL(); };
    seg.append(b);
  }
  row(light, 'Preset').append(seg);
  if (display.light === 'day') {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    slider(light, 'Sun, solar time', 'hour', 6, 20, 0.25, h => `${Math.floor(h)}:${String(Math.round(h % 1 * 60)).padStart(2, '0')}`);
    slider(light, 'Month', 'month', 1, 12, 1, m => months[m - 1]);
  }
  slider(light, 'Exposure', 'exposure', -2, 2, 0.1, e => (e > 0 ? '+' : '') + e.toFixed(1));

  const ev = section('Evidence & site');
  if (contract.scan) {
    const r = check(ev, 'Scan points', 'scan', applyEvidence);
    const n = document.createElement('div'); n.className = 'note'; n.textContent = contract.scan.note; r.append(n);
  }
  check(ev, 'Ghost the model', 'ghost', applyEvidence);
  const sheets = Object.assign(document.createElement('a'), {href: 'scan/sheets/', className: 'drawings', textContent: 'Scan vs model sheets ↗', target: '_blank'});
  ev.append(sheets);
  check(ev, 'Lot lines', 'lot', applyEvidence);

  const files = section('Save & share');
  const btn = (label, fn) => { const b = document.createElement('button'); b.className = 'wide'; b.textContent = label; b.onclick = fn; files.append(b); };
  btn('Save choices (.json)', saveChoices);
  const lab = document.createElement('label');
  lab.className = 'wide filepick';
  lab.innerHTML = 'Load choices <input type="file" accept="application/json">';
  lab.querySelector('input').onchange = e => loadChoices(e.target.files[0]);
  files.append(lab);
  btn('Save this view (.png)', savePNG);
  btn('Download this design (.glb)', saveGLB);
  const keys = document.createElement('p');
  keys.className = 'note';
  keys.textContent = 'Keys: 1-9 jump to views, F for full screen, Esc to leave it.';
  files.append(keys);
  if (stats) out.push(modelDetails());
  return out;
}

// ---------------------------------------------------------------- model details
// What the model on screen weighs, from site/stats.json (the build writes it), and the work log
// of the sessions that built it when model/worklog.yml exists. A hint over 15 MB or 1,000 draw
// calls, never a cap: nothing here decimates or splits a model.
let stats = null, detailsOpen = false;
const HEAVY_BYTES = 15e6, HEAVY_DRAW_CALLS = 1000;
const bytes = n => n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
const count = n => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n.toLocaleString('en-US');
const dollars = n => n >= 100 ? `$${Math.round(n).toLocaleString('en-US')}` : `$${n.toFixed(2)}`;
const modelName = id => { const m = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(id); return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}` : id; };
function onScreen() {
  // The files the current settings load: the shell, each slot's GLB, and the scan layer when it's on.
  const rels = ['model/house.glb', ...Object.values(contract.slots).map(t => t.replace(/\{(\w+)\}/g, (_, k) => settings[k]))];
  if (display.scan && contract.scan) rels.push(contract.scan.url);
  return rels.map(r => stats.files[r]).filter(Boolean);
}
function refreshDetails() {
  const old = document.querySelector('fieldset.details');
  if (old && stats) old.replaceWith(modelDetails());
}
function modelDetails() {
  const fs = document.createElement('fieldset');
  fs.className = 'details';
  const d = document.createElement('details');
  d.open = detailsOpen;
  d.ontoggle = () => { detailsOpen = d.open; };
  const sum = (rows, k) => rows.reduce((n, r) => n + (r[k] || 0), 0);
  const now = onScreen(), all = Object.values(stats.files);
  const wire = rows => rows.every(r => r.br_bytes) ? `${bytes(sum(rows, 'br_bytes'))} brotli` : `${bytes(sum(rows, 'gz_bytes'))} gzipped`;
  const summary = document.createElement('summary');
  summary.innerHTML = `Model details <span>${bytes(sum(now, 'bytes'))}</span>`;
  d.append(summary);
  if (sum(now, 'bytes') > HEAVY_BYTES || sum(now, 'meshes') > HEAVY_DRAW_CALLS) {
    const h = document.createElement('p'); h.className = 'note heavy'; h.textContent = 'Large model: first load takes longer on a phone.'; d.append(h);
  }
  const facts = [
    ['On screen', `${bytes(sum(now, 'bytes'))}, ${wire(now)}`],
    ['Triangles', count(sum(now, 'triangles'))],
    ['Vertices', count(sum(now, 'vertices'))],
    ['Draw calls', count(sum(now, 'meshes'))],
    ['Materials', count(sum(now, 'materials'))],
    ['Textures', sum(now, 'images') ? `${sum(now, 'images')} (${bytes(sum(now, 'image_bytes'))})` : 'none'],
    ['Scan points', sum(now, 'scan_points') ? count(sum(now, 'scan_points')) : 'off'],
    ['Every option', `${all.length} files, ${bytes(sum(all, 'bytes'))} (${wire(all)})`],
  ];
  const dl = document.createElement('dl');
  for (const [k, v] of facts) {
    const div = document.createElement('div');
    div.innerHTML = `<dt>${k}</dt><dd>${v}</dd>`;
    dl.append(div);
  }
  d.append(dl);
  if (stats.worklog) d.append(workLog(stats.worklog));
  fs.append(d);
  return fs;
}
function workLog(log) {
  const sec = document.createElement('section');
  sec.className = 'worklog';
  sec.setAttribute('aria-label', 'Work log');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const roles = s => Object.entries(s.roles).map(([r, v]) => `${r} ${[...new Set(v.models.map(modelName))].join(', ')}`).join('; ');
  const rows = log.sessions.map(s => `<tr><td>${esc(s.date)}</td><td>${esc(s.title)}<small>${esc(s.session)} · ${esc(roles(s))} · ${count(s.turns)} turns</small></td>` +
    `<td>${count(s.tokens)}</td><td>${dollars(s.cost)}${s.unpriced ? '+' : ''}</td></tr>`).join('');
  const t = log.total;
  sec.innerHTML = `<h3>Work log</h3><p class="note">Sessions that built this model, as far as they could be attributed. ` +
    `Cost is the API list-price equivalent (prices as of ${esc(log.prices_as_of)}), not a bill.</p>` +
    `<table><thead><tr><th>Date</th><th>Session</th><th>Tokens</th><th>Cost equiv.</th></tr></thead><tbody>${rows}</tbody>` +
    `<tfoot><tr><td colspan="2">Total, ${log.sessions.length} ${log.sessions.length === 1 ? 'session' : 'sessions'}</td>` +
    `<td>${count(t.tokens)}</td><td>${dollars(t.cost)}${t.unpriced ? '+' : ''}</td></tr></tfoot></table>`;
  return sec;
}

// ---------------------------------------------------------------- save and share
function download(blob, name) {
  const a = Object.assign(document.createElement('a'), {href: URL.createObjectURL(blob), download: name});
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function saveChoices() {
  download(new Blob([JSON.stringify({choices: proposed(), display, view: views[selected].name}, null, 1)], {type: 'application/json'}), 'house-choices.json');
}
async function loadChoices(file) {
  if (!file) return;
  try {
    const d = JSON.parse(await file.text());
    if (state === 'existing') await setState('proposed');
    Object.assign(settings, d.choices || {});
    Object.assign(display, d.display || {});
    fix(settings);
    buildPanel();
    await applySlots();
    const i = views.findIndex(v => v.name === d.view);
    if (i >= 0) showView(i);
    toast('Choices loaded');
  } catch { toast("That file isn't a choices file"); }
}
function savePNG() {
  renderer.render(scene, camera);   // capture in the same task as the render: no preserveDrawingBuffer needed
  renderer.domElement.toBlob(b => download(b, 'house-view.png'), 'image/png');
}
function saveGLB() {
  // What's on screen: the shell plus the chosen slot files, with the chosen colors.
  new GLTFExporter().parse(root, r => download(new Blob([r], {type: 'model/gltf-binary'}), 'house-design.glb'), () => toast('Export failed'), {binary: true});
}
addEventListener('keydown', e => {
  if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || walking || e.metaKey || e.ctrlKey) return;
  if (/^[1-9]$/.test(e.key) && views[Number(e.key) - 1]) showView(Number(e.key) - 1);
  if (e.key === 'f' || e.key === 'F') document.body.classList.toggle('full');
  if (e.key === 'Escape') document.body.classList.remove('full');
});
function note(f) {
  const div = document.createElement('div');
  div.className = 'note';
  const o = f.options[settings[f.id]];
  const spec = f.id === 'door' ? contract.door_specs[settings.door] : null;
  if (spec) {
    div.innerHTML = `<b>${o.maker} ${o.model}</b><br>Unit ${spec.unit}` +
      (spec.rough_opening ? ` · rough opening ${spec.rough_opening}` : '') +
      ` · jamb ${spec.jamb}` + (spec.glass ? `<br>${spec.glass}` : '') +
      (o.note ? `<br>${o.note}` : '') + `<br><a href="${o.url}" target="_blank" rel="noopener">Spec sheet ↗</a>`;
  } else div.textContent = o.note || '';
  return div;
}
async function set(id, value) {
  settings[id] = value;
  fix(settings);
  buildPanel();
  applyColors();
  syncURL();
  await applySlots();
}
$('panel-toggle').onclick = () => {
  const open = document.body.classList.toggle('panel-open');
  $('panel-toggle').setAttribute('aria-expanded', open);
};

// ---------------------------------------------------------------- views and links
function showView(i, animate = true) {
  selected = (i + views.length) % views.length;
  $('view').value = selected;
  const v = views[selected];
  if (walking) walk(false);
  clip = v.section ?? null;
  applyClip();
  fly = animate ? {fromPos: camera.position.clone(), fromTarget: orbit.target.clone(), toPos: new THREE.Vector3(...v.eye), toTarget: new THREE.Vector3(...v.target), t: 0} : null;
  if (!animate) { camera.position.set(...v.eye); orbit.target.set(...v.target); orbit.update(); }
  syncURL();
}
// Plan cuts: a view with `section` clips everything above that height and shows the cut
// walls from inside (double-sided), so it reads as a floor plan from above.
let clip = null;
const clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
function applyClip() {
  if (clip != null) clipPlane.constant = clip;
  renderer.clippingPlanes = clip != null ? [clipPlane] : [];
  root.traverse(o => { if (o.isMesh) { o.material.side = clip != null ? THREE.DoubleSide : THREE.FrontSide; } });
}
$('prev-view').onclick = () => showView(selected - 1);
$('next-view').onclick = () => showView(selected + 1);
$('view').onchange = e => showView(Number(e.target.value));

function linkURL() {
  const p = new URLSearchParams();
  const s = proposed();
  for (const f of fields.values()) {
    const v = s[f.id];
    if (v !== (f.default ?? optionKeys(f)[0])) p.set(f.id, f.kind === 'toggle' ? Number(v) : v);
  }
  if (state === 'existing') p.set('state', 'existing');
  for (const [k, v] of Object.entries(display)) if (v !== DISPLAY_DEFAULTS[k]) p.set(k, typeof v === 'boolean' ? Number(v) : v);
  p.set('view', views[selected].name.toLowerCase().replace(/\W+/g, '-'));
  return location.pathname + '?' + p;
}
// The other way: a link's settings, light and state (at start, and for a comment's "Go there").
function readQuery(q) {
  settings = defaults();
  for (const f of fields.values()) if (q.has(f.id)) settings[f.id] = f.kind === 'range' ? Number(q.get(f.id)) : q.get(f.id);
  fix(settings);
  Object.assign(display, DISPLAY_DEFAULTS);
  for (const k of Object.keys(display)) if (q.has(k)) display[k] = typeof display[k] === 'boolean' ? q.get(k) === '1' : typeof display[k] === 'number' ? Number(q.get(k)) : q.get(k);
  if (!LIGHTS[display.light]) display.light = 'day';
  state = 'proposed'; proposedSettings = null;
  if (q.get('state') === 'existing') { proposedSettings = {...settings}; settings = fix({...settings, ...contract.existing}); state = 'existing'; }
  document.body.dataset.state = state;
}
// The named view, then `cam` (eye and target, six numbers) if the link has one: comments do.
function viewFromQuery(q) {
  const vi = views.findIndex(v => v.name.toLowerCase().replace(/\W+/g, '-') === q.get('view'));
  showView(vi < 0 ? 0 : vi, false);
  const cam = (q.get('cam') || '').split(',').map(Number);
  if (cam.length === 6 && cam.every(Number.isFinite)) { camera.position.fromArray(cam); orbit.target.fromArray(cam, 3); orbit.update(); }
}
function syncURL() {
  clearTimeout(syncURL.t);
  syncURL.t = setTimeout(() => { try { history.replaceState(null, '', linkURL()); } catch {} }, 200);
}
$('share').onclick = async () => {
  const url = location.origin + linkURL();
  try { if (navigator.share) await navigator.share({url}); else { await navigator.clipboard.writeText(url); toast('Link copied'); } } catch {}
};
function toast(s) {
  $('toast').textContent = s;
  $('toast').classList.add('on');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => $('toast').classList.remove('on'), 2500);
}

// ---------------------------------------------------------------- walk
// Walk: the left thumb on the stick walks, the right thumb drags the canvas to look;
// keys on a desktop. Keeps the view you had, speeds up while held, double-tap to go there.
const WALK_SPEED = 1.5, JOG = 2.5, RISE_SPEED = 1, STICK_RADIUS = 48, EYE_HEIGHT = 1.6, WALL_STANDOFF = 0.6, FLOOR_PITCH = -0.14;
const HOLD_GRACE = 1.2, HOLD_RAMP = 2.5, HOLD_TOP = 3;   // walking pace for nudges, up to 3x to cross the yard
const DOUBLE_TAP_MS = 350, DOUBLE_TAP_PX = 30, TAP_SLOP_PX = 10;  // iOS Safari sends no dblclick for touches
const keys = new Set(), stick = [0, 0], rotation = new THREE.Euler(0, 0, 0, 'YXZ');
let walking = false, look = null, lastTime = 0, held = 0, jog = false, glide = null, fly = null;

function holdPace(t) { const k = Math.min(1, Math.max(0, (t - HOLD_GRACE) / HOLD_RAMP)); return 1 + (HOLD_TOP - 1) * k * k * (3 - 2 * k); }
// A floor (face pointing up) stands you on it at eye height; anything else stops you short of it.
function teleportTo(from, hit, normalY) {
  if (normalY > 0.7) return new THREE.Vector3(hit.x, hit.y + EYE_HEIGHT, hit.z);
  const dx = hit.x - from.x, dz = hit.z - from.z, flat = Math.hypot(dx, dz);
  if (flat <= WALL_STANDOFF) return from.clone();
  const keep = (flat - WALL_STANDOFF) / flat;
  return new THREE.Vector3(from.x + dx * keep, from.y, from.z + dz * keep);
}
function resetStick() { stick[0] = stick[1] = 0; $('walk-knob').style.transform = ''; }
function walk(on) {
  walking = on;
  orbit.enabled = !on;
  $('walk-pad').hidden = !on;
  document.body.classList.toggle('walking', on);
  $('walk').textContent = on ? 'Finish' : 'Walk';
  fly = glide = look = null; held = 0; keys.clear(); resetStick();
  if (on) {
    // Walk from right here, looking where you were; only level the roll.
    camera.up.set(0, 1, 0);
    rotation.setFromQuaternion(camera.quaternion, 'YXZ');
    rotation.z = 0;
    camera.quaternion.setFromEuler(rotation);
  } else {
    const d = new THREE.Vector3();
    camera.getWorldDirection(d);
    orbit.target.copy(camera.position).addScaledVector(d, 3);
    orbit.update();
  }
}
$('walk').onclick = () => walk(!walking);
$('finish-walk').onclick = () => walk(false);
{ // the stick: analogue, clamped to its rim, so a gentle push is a slow walk
  const pad = $('walk-stick'), knob = $('walk-knob');
  const move = e => {
    const b = pad.getBoundingClientRect();
    let x = (e.clientX - b.left - b.width / 2) / STICK_RADIUS, y = -(e.clientY - b.top - b.height / 2) / STICK_RADIUS;
    const over = Math.max(1, Math.hypot(x, y));
    x /= over; y /= over;
    stick[0] = x; stick[1] = y;
    knob.style.transform = `translate(${x * STICK_RADIUS}px,${-y * STICK_RADIUS}px)`;
  };
  pad.onpointerdown = e => { try { pad.setPointerCapture(e.pointerId); } catch {} move(e); };
  pad.onpointermove = e => { if (pad.hasPointerCapture(e.pointerId)) move(e); };
  pad.onpointerup = pad.onpointercancel = resetStick;
}
// Canvas: look in Walk, double-tap anywhere. Track clientX ourselves: iOS leaves movementX at 0 for touches.
const canvas = renderer.domElement, raycaster = new THREE.Raycaster(), pointers = new Set();
let press = null, lastTap = null;
const solid = h => {
  const m = [].concat(h.object.material)[0];
  return h.object.isMesh && h.object.visible && !(m?.transparent && m.opacity < 0.9)   // glass doesn't stop a tap
    && (clip == null || h.point.y <= clip);                                              // nor does what a plan cut removed
};
function pick(cx, cy) {
  const b = canvas.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((cx - b.left) / b.width * 2 - 1, -(cy - b.top) / b.height * 2 + 1), camera);
  return raycaster.intersectObject(root, true).find(solid) || null;
}
function goTo(cx, cy) {
  const hit = pick(cx, cy);
  if (!hit?.face) return;
  if (walking) {
    const ny = hit.face.normal.clone().transformDirection(hit.object.matrixWorld).y, floor = ny > 0.7;
    glide = {from: camera.position.clone(), to: teleportTo(camera.position, hit.point, ny), fromPitch: rotation.x, toPitch: floor ? Math.max(rotation.x, FLOOR_PITCH) : rotation.x, t: 0};
    return;
  }
  const away = camera.position.clone().sub(hit.point), dist = Math.min(12, Math.max(3, away.length() * 0.5));
  fly = {fromPos: camera.position.clone(), fromTarget: orbit.target.clone(), toPos: hit.point.clone().add(away.setLength(dist)), toTarget: hit.point.clone(), t: 0};
}
canvas.addEventListener('pointerdown', e => {
  pointers.add(e.pointerId);
  press = pointers.size === 1 ? {x: e.clientX, y: e.clientY} : null;   // a pinch is not a tap
  if (walking && !look) { look = {id: e.pointerId, x: e.clientX, y: e.clientY}; try { canvas.setPointerCapture(e.pointerId); } catch {} }   // best-effort: the pointer can be gone already
});
canvas.addEventListener('pointermove', e => {
  if (!walking || !look || e.pointerId !== look.id) return;
  rotation.y -= (e.clientX - look.x) * 0.004;
  rotation.x = Math.max(-1.5, Math.min(1.5, rotation.x - (e.clientY - look.y) * 0.004));
  look.x = e.clientX; look.y = e.clientY;
  camera.quaternion.setFromEuler(rotation);
});
canvas.addEventListener('pointerup', e => {
  pointers.delete(e.pointerId);
  if (look?.id === e.pointerId) look = null;
  if (!press || Math.hypot(e.clientX - press.x, e.clientY - press.y) > TAP_SLOP_PX) { press = null; return; }
  press = null;
  const tap = {x: e.clientX, y: e.clientY, at: performance.now()};
  if (noting) { if (tool === 'point') addPin(tap.x, tap.y); return; }   // commenting: a tap is a pin, not a flight
  if (lastTap && tap.at - lastTap.at < DOUBLE_TAP_MS && Math.hypot(tap.x - lastTap.x, tap.y - lastTap.y) < DOUBLE_TAP_PX) { lastTap = null; goTo(tap.x, tap.y); return; }
  lastTap = tap;
});
canvas.addEventListener('pointercancel', e => { pointers.delete(e.pointerId); if (look?.id === e.pointerId) look = null; press = null; });
orbit.addEventListener('start', () => { fly = null; });
const moveKeys = {w: 'forward', s: 'backward', a: 'left', d: 'right', q: 'down', e: 'up', arrowup: 'forward', arrowdown: 'backward', arrowleft: 'left', arrowright: 'right', pageup: 'up', pagedown: 'down'};
addEventListener('keydown', e => {
  if (!walking || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
  jog = e.shiftKey;
  if (e.key === 'Escape') { walk(false); return; }
  const m = moveKeys[e.key.toLowerCase()];
  if (m) { keys.add(m); e.preventDefault(); }
});
addEventListener('keyup', e => { jog = e.shiftKey; keys.delete(moveKeys[e.key.toLowerCase()]); });
addEventListener('blur', () => { keys.clear(); jog = false; resetStick(); });   // a key can stick down across an alt-tab
for (const b of document.querySelectorAll('[data-move]')) {
  b.onpointerdown = e => { keys.add(b.dataset.move); try { b.setPointerCapture(e.pointerId); } catch {} };
  b.onpointerup = b.onpointercancel = () => keys.delete(b.dataset.move);
}

// ---------------------------------------------------------------- comment
// Tap things to drop numbered pins (each keeps its 3D point and what it hit), or draw with the
// pen, then write a note. Send posts it with a picture of the view to worker/index.js (D1);
// tools/comments.py (make comments) is how an agent reads and answers them. Pen strokes are
// drawn on the screen, not in 3D, so the view holds still while there is drawing on it.
// The button only shows where /api/comments answers: GitHub Pages and `make serve` have no API.
let noting = false, tool = 'point', pins = [], strokes = [], undo = [], inkStroke = null;
const ink = $('ink'), inkCtx = ink.getContext('2d'), INK = '#c4561a';
// What a pin hit. Pieces can carry glTF extras kp_id / kp_label (GLTFLoader puts them in
// userData); without them it's the node's name, which here is the material's (paint.trim), and its slot.
function pieceOf(o) {
  let id = null, label = null, name = null, slot = null;
  for (; o; o = o.parent) { id ??= o.userData.kp_id; label ??= o.userData.kp_label; name ??= o.userData.name; slot ??= o.userData.slot; }
  return {id: id || name || null, label: label || (name ? (slot && slot !== 'shell' ? `${name} (${slot})` : name) : null)};
}
function sizeInk() { const r = Math.min(devicePixelRatio, 2); ink.width = innerWidth * r; ink.height = innerHeight * r; drawInk(); }
addEventListener('resize', sizeInk);
function drawInk() {
  const r = ink.width / innerWidth;
  inkCtx.setTransform(r, 0, 0, r, 0, 0);
  inkCtx.clearRect(0, 0, innerWidth, innerHeight);
  Object.assign(inkCtx, {lineCap: 'round', lineJoin: 'round', lineWidth: 4, strokeStyle: INK});
  for (const st of strokes) {
    inkCtx.beginPath();
    st.forEach(([x, y], i) => i ? inkCtx.lineTo(x, y) : inkCtx.moveTo(x, y));
    if (st.length === 1) inkCtx.lineTo(st[0][0] + 0.1, st[0][1]);   // a dot
    inkCtx.stroke();
  }
}
function hint() {
  $('note-hint').textContent = tool === 'pen' ? 'Draw on the view. It holds still while there is drawing on it; Undo to free it.'
    : strokes.length ? 'Tap things to number them. The view holds still while there is drawing on it.'
    : 'Tap things to number them. Drag to move around; pins stay put.';
  orbit.enabled = !noting || (tool === 'point' && !strokes.length);
  document.body.classList.toggle('inking', noting && tool === 'pen');
  for (const b of document.querySelectorAll('#note-tool button')) b.setAttribute('aria-pressed', b.dataset.tool === tool);
  $('note-undo').disabled = !undo.length;
}
function setTool(t) { tool = t; hint(); }
function addPin(x, y) {
  const hit = pick(x, y);
  if (!hit) { if (display.ghost) toast('Turn off “Ghost the model” to point at things'); return; }
  const {id, label} = pieceOf(hit.object);
  const el = document.createElement('div');
  el.className = 'pin';
  el.textContent = pins.length + 1;
  $('pins').append(el);
  pins.push({point: hit.point.clone(), id, label, el});
  undo.push('pin');
  if (label) toast(`${pins.length}: ${label}`);
  hint();
}
const pinAt = new THREE.Vector3();
function placePins() {
  for (const p of pins) {
    pinAt.copy(p.point).project(camera);
    const off = pinAt.z > 1 || Math.abs(pinAt.x) > 1.1 || Math.abs(pinAt.y) > 1.1;
    p.el.hidden = off;
    if (!off) { p.el.style.left = (pinAt.x + 1) / 2 * innerWidth + 'px'; p.el.style.top = (1 - pinAt.y) / 2 * innerHeight + 'px'; }
  }
}
function clearNote() { for (const p of pins) p.el.remove(); pins = []; strokes = []; undo = []; drawInk(); }
function noteMode(on) {
  noting = on;
  document.body.classList.toggle('noting', on);
  $('note').hidden = !on;
  if (on) {
    if (walking) walk(false);
    if (touring) playTour(null);
    document.body.classList.remove('panel-open');
    sizeInk(); setTool('point'); loadNotes();
  } else { clearNote(); orbit.enabled = true; document.body.classList.remove('inking'); }
}
$('comment').onclick = () => noteMode(true);
$('note-cancel').onclick = () => noteMode(false);
for (const b of document.querySelectorAll('#note-tool button')) b.onclick = () => setTool(b.dataset.tool);
$('note-undo').onclick = () => { const last = undo.pop(); if (last === 'pin') pins.pop().el.remove(); else if (last === 'stroke') { strokes.pop(); drawInk(); } hint(); };
ink.addEventListener('pointerdown', e => { if (tool !== 'pen') return; ink.setPointerCapture(e.pointerId); inkStroke = [[e.clientX, e.clientY]]; strokes.push(inkStroke); undo.push('stroke'); drawInk(); hint(); });
ink.addEventListener('pointermove', e => { if (!inkStroke || !ink.hasPointerCapture(e.pointerId)) return; inkStroke.push([e.clientX, e.clientY]); drawInk(); });
ink.addEventListener('pointerup', () => { inkStroke = null; });
ink.addEventListener('pointercancel', () => { inkStroke = null; });
addEventListener('keydown', e => { if (e.key === 'Escape' && noting) noteMode(false); });
const camKey = () => [...camera.position.toArray(), ...orbit.target.toArray()].map(v => v.toFixed(3)).join(',');
// The picture: this frame, the pen on top, the pins as numbered dots, at most 1600 px wide.
// Render and read in the same task, so the frame is still there without preserveDrawingBuffer.
function snapshot() {
  renderer.render(scene, camera);
  const src = renderer.domElement, k = Math.min(1, 1600 / src.width), w = Math.round(src.width * k), h = Math.round(src.height * k);
  const out = Object.assign(document.createElement('canvas'), {width: w, height: h}), g = out.getContext('2d');
  g.drawImage(src, 0, 0, w, h);
  g.drawImage(ink, 0, 0, w, h);
  const s = w / innerWidth;
  placePins();
  for (const p of pins) {
    if (p.el.hidden) continue;
    const x = parseFloat(p.el.style.left) * s, y = parseFloat(p.el.style.top) * s, r = 13 * s;
    g.fillStyle = '#fff'; g.beginPath(); g.arc(x, y, r + 2 * s, 0, 7); g.fill();
    g.fillStyle = INK; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    Object.assign(g, {fillStyle: '#fff', font: `600 ${13 * s}px system-ui, sans-serif`, textAlign: 'center', textBaseline: 'middle'});
    g.fillText(p.el.textContent, x, y + 0.5);
  }
  return out.toDataURL('image/jpeg', 0.82);
}
try { $('note-author').value = localStorage.getItem('note-author') || ''; } catch {}
$('note-send').onclick = async () => {
  const body = $('note-body').value.trim();
  if (!body && !pins.length && !strokes.length) { toast('Write a note, tap something, or draw first'); return; }
  const author = $('note-author').value.trim();
  try { localStorage.setItem('note-author', author); } catch {}
  const c = {model: contract.name, author, body, link: `${location.origin}${linkURL()}&cam=${camKey()}`, show: state, cam: camKey(),
    pins: pins.map(p => ({x: p.point.x, y: p.point.y, z: p.point.z, id: p.id, label: p.label})), strokes: strokes.length,
    image: snapshot(), website: $('note-website').value};
  $('note-send').disabled = true;
  try {
    const r = await fetch('api/comments', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(c)});
    if (!r.ok) throw Error((await r.json().catch(() => ({}))).error || r.status);
    // Keep the tool they were using: back in Point, a drag orbits instead of drawing the next circle.
    $('note-body').value = ''; clearNote(); hint(); toast('Sent. Thanks!'); loadNotes(true);
  } catch (e) { console.error(e); toast('That didn’t send. Try again in a moment.'); }
  finally { $('note-send').disabled = false; }
};
// Earlier notes for this model, with the replies; "Go there" restores the design, light and camera.
const esc = s => String(s ?? '').replace(/[&<>"]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[ch]);
const fetchNotes = () => fetch(`api/comments?model=${encodeURIComponent(contract.name)}`, {cache: 'no-store'}).then(r => { if (!r.ok) throw Error(r.status); return r.json(); });
async function loadNotes(openList) {
  const list = $('note-list'), ol = list.querySelector('ol');
  try {
    const {comments} = await fetchNotes();
    list.querySelector('summary').textContent = `Earlier notes (${comments.length})`;
    if (openList) list.open = true;
    ol.innerHTML = comments.map(c => `<li><div class="meta">${esc(c.author || 'Someone')} · ${new Date(c.created).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}` +
      `${c.status === 'open' ? ' · open' : ` · <span class="${c.status === 'done' ? 'done' : ''}">${esc(c.status)}</span>`}</div>${esc(c.body) || '<i>(drawing only)</i>'}` +
      `${c.pins.length ? `<div class="meta">${c.pins.map(p => `${p.n}: ${esc(p.label || 'a spot')}`).join(' · ')}</div>` : ''}` +
      `${c.reply ? `<div class="reply">${esc(c.reply)}</div>` : ''}` +
      `<div class="acts"><button data-link="${esc(c.link)}">Go there</button>${c.has_image ? `<a href="api/comments/${esc(c.id)}.jpg" target="_blank" rel="noopener">Picture</a>` : ''}</div></li>`).join('')
      || '<li class="meta">No notes yet.</li>';
    for (const b of ol.querySelectorAll('[data-link]')) b.onclick = () => goThere(b.dataset.link);
  } catch (e) { console.error(e); list.querySelector('summary').textContent = 'Earlier notes (couldn’t load)'; }
}
async function goThere(link) {
  const q = new URL(link, location.href).searchParams;
  readQuery(q);
  buildPanel();
  await applySlots();
  viewFromQuery(q);
}
function commentsOn() { fetchNotes().then(d => { if (Array.isArray(d.comments)) $('comment').hidden = false; }).catch(() => {}); }

// ---------------------------------------------------------------- tours
// A tour is keyframes: camera eye and target at a time, and optionally settings to apply
// (a slider eases between keys; anything else switches at its key). Catmull-Rom through
// the keys makes the path smooth; the picture depends only on t, so a recording can
// step through it frame by frame (tools/record_tour.py).
let touring = null;
function catmull(p0, p1, p2, p3, u) {
  const u2 = u * u, u3 = u2 * u;
  return p1.map((_, i) => 0.5 * (2 * p1[i] + (-p0[i] + p2[i]) * u + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * u2 + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * u3));
}
function tourPose(tour, t) {
  const k = tour.keys, n = k.length;
  let i = 0;
  while (i < n - 2 && t > k[i + 1].at) i++;
  const span = k[i + 1].at - k[i].at, u = Math.min(1, Math.max(0, (t - k[i].at) / span));
  const e = u * u * (3 - 2 * u) * 0.35 + u * 0.65;   // a touch of ease at each key
  const at = j => k[Math.max(0, Math.min(n - 1, j))];
  return {eye: catmull(at(i - 1).eye, at(i).eye, at(i + 1).eye, at(i + 2).eye, e),
          target: catmull(at(i - 1).target, at(i).target, at(i + 1).target, at(i + 2).target, e)};
}
function tourSettings(tour, t) {
  const out = {};
  for (const id of new Set(tour.keys.flatMap(k => Object.keys(k.set || {})))) {
    const with_ = tour.keys.filter(k => k.set && id in k.set);
    const before = with_.filter(k => k.at <= t).pop(), after = with_.find(k => k.at > t);
    if (!before) continue;
    const f = fields.get(id);
    if (f?.kind === 'range' && after) {
      const u = Math.min(1, (t - before.at) / (after.at - before.at)), s = u * u * (3 - 2 * u);
      out[id] = before.set[id] + (after.set[id] - before.set[id]) * s;
    } else out[id] = before.set[id];
  }
  return out;
}
async function tourFrame(tour, t, live = false) {
  const want = tourSettings(tour, t);
  let swap = false;
  for (const [id, v] of Object.entries(want)) {
    if (settings[id] === v) continue;
    settings[id] = fields.get(id).kind === 'range' ? v : String(v);
    if (fields.get(id).kind !== 'range') swap = true;
  }
  if (swap) { fix(settings); await applySlots(); buildPanel(); } else { applyRanges(); }
  if (live && touring?.tour !== tour) return;   // stopped while a model was loading: don't move the camera after Stop
  const pose = tourPose(tour, t);
  camera.position.set(...pose.eye);
  orbit.target.set(...pose.target);
  camera.lookAt(orbit.target);
}
function playTour(tour) {
  if (walking) walk(false);
  if (tour && state === 'existing') setState('proposed');
  touring = tour ? {tour, start: performance.now(), busy: false} : null;
  $('tour').textContent = touring ? 'Stop' : 'Tour';
  orbit.enabled = !touring;
}
$('tour').onclick = () => playTour(touring ? null : contract.tours[Number($('tour-pick').value) || 0]);

const ease = t => 1 - (1 - t) ** 3;
renderer.setAnimationLoop(time => {
  if (touring) {
    const t = (performance.now() - touring.start) / 1000, end = touring.tour.keys.at(-1).at;
    if (!touring.busy) { touring.busy = true; tourFrame(touring.tour, Math.min(t, end), true).then(() => { if (touring) touring.busy = false; }); }
    if (t > end + 0.5) playTour(null);
    renderer.render(scene, camera);
    return;
  }
  const dt = Math.min(0.05, (time - lastTime) / 1000);
  lastTime = time;
  if (walking) {
    let x = stick[0], y = stick[1], z = 0;
    for (const k of keys) { if (k === 'forward') y++; if (k === 'backward') y--; if (k === 'right') x++; if (k === 'left') x--; if (k === 'up') z++; if (k === 'down') z--; }
    if (x || y || z) {
      glide = null; held += dt;
      const f = new THREE.Vector3(); camera.getWorldDirection(f); f.y = 0; f.normalize();
      const r = new THREE.Vector3().crossVectors(f, new THREE.Vector3(0, 1, 0));
      // Level whichever way you look; two keys held aren't faster than one.
      const step = WALK_SPEED * (jog ? JOG : 1) * holdPace(held) * dt / Math.max(1, Math.hypot(x, y));
      camera.position.addScaledVector(f, y * step).addScaledVector(r, x * step);
      camera.position.y += z * RISE_SPEED * dt;
    } else held = 0;
    if (glide) {
      glide.t = Math.min(1, glide.t + dt / 0.45);
      const k = ease(glide.t);
      camera.position.lerpVectors(glide.from, glide.to, k);
      rotation.x = glide.fromPitch + (glide.toPitch - glide.fromPitch) * k;
      camera.quaternion.setFromEuler(rotation);
      if (glide.t >= 1) glide = null;
    }
  } else {
    if (fly) {
      fly.t = Math.min(1, fly.t + dt / 0.6);
      const k = ease(fly.t);
      camera.position.lerpVectors(fly.fromPos, fly.toPos, k);
      orbit.target.lerpVectors(fly.fromTarget, fly.toTarget, k);
      if (fly.t >= 1) fly = null;
    }
    orbit.update();
  }
  updateCompass();
  renderer.render(scene, camera);
  if (noting) placePins();
});

// ---------------------------------------------------------------- start
(async () => {
  contract = await (await fetch('controls.json')).json();
  stats = await fetch('stats.json').then(r => r.ok ? r.json() : null).catch(() => null);   // optional: no file, no details
  for (const s of contract.sections) for (const f of s.fields) fields.set(f.id, f);
  views = contract.views;
  for (const [i, v] of views.entries()) $('view').add(new Option(v.name, i));
  const q = new URLSearchParams(location.search);
  readQuery(q);
  buildLamps();
  buildLot();
  buildPanel();
  const shell = (await load('model/house.glb')).clone(true);
  shell.userData.slot = 'shell';
  shell.traverse(o => { if (o.isMesh) o.castShadow = o.receiveShadow = true; });
  root.add(shell);
  await applySlots();
  viewFromQuery(q);
  commentsOn();   // shows the Comment button only where /api/comments answers (not on GitHub Pages)
  for (const [i, t] of (contract.tours || []).entries()) $('tour-pick').add(new Option(t.name, i));
  window.viewer = {THREE, scene, camera, renderer, sun, root, orbit, settings: () => settings, set, setState, state: () => state, display, applyLight, slots: () => Object.fromEntries([...slots].map(([k, v]) => [k, v.url])), walkPace: () => holdPace(held), touch: () => ({pointers: pointers.size, walking, glide: !!glide}), moving: () => !!(fly || glide || touring),   // for tests and the console
    tours: contract.tours,
    // one deterministic frame of a tour, as a JPEG data URL: what tools/record_tour.py captures
    async tourFrame(i, t) { renderer.setAnimationLoop(null); await tourFrame(contract.tours[i], t); renderer.render(scene, camera); return renderer.domElement.toDataURL('image/jpeg', 0.92); }};
  if (q.has('tour')) playTour(contract.tours.find(t => t.name.toLowerCase().replace(/\W+/g, '-') === q.get('tour')) || contract.tours[0]);
  $('loading').remove();
  document.body.classList.add('ready');
})();
