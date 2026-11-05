"""The in-browser 3D map page (`/view3d`): one or several maps (from up to 3 jobs), drawn side by side in a single WebGL2 canvas,
or as the difference of exactly two maps, with an optional see-through mask shell and an optional second map (local resolution) as colour.
URL params read by the page itself: mode=diff, rx, ry (start rotation, degrees), level (real units or auto), detail, render=gpu|soft|auto,
chrome=1 (no toolbar; for `reliontree render`).

Own small raymarcher (orthographic, first hit on the iso-level, gradient shading), vanilla JS inlined into the page, no
CDN, no library: it has to work on an offline HPC login node over a tunnel. The cubes come from /volume (relion_volume.py).
The data keeps its handedness (x right, y up, z towards the viewer, voxel order as in the file): nothing is flipped.
"""
import json

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>reliontree 3D</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f6f7f9;--fg:#1d2433;--bar:#fff;--line:#d5d9e0}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e4e7ec;--bar:#1d2129;--line:#343a46}}
html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font:13px system-ui,sans-serif}
#bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:8px 12px;background:var(--bar);border-bottom:1px solid var(--line)}
#bar label{display:flex;align-items:center;gap:6px;white-space:nowrap}
#bar input[type=range]{width:160px}
body{display:flex;flex-direction:column;overflow:hidden}#stage{position:relative;flex:1;min-height:0}
body.chrome #bar{display:none}
#legend{position:absolute;right:10px;bottom:10px;padding:6px 8px;border-radius:6px;background:rgba(0,0,0,.6);color:#fff;font-size:12px;display:none}
#legend i{display:block;width:160px;height:10px;margin:3px 0;background:linear-gradient(90deg,#2b4fd8,#25b7d3,#f0e442,#d9382b)}
#legend span{display:flex;justify-content:space-between}
canvas{width:100%;height:100%;display:block;touch-action:none;cursor:grab}
.tag{position:absolute;padding:2px 6px;border-radius:4px;background:rgba(0,0,0,.55);color:#fff;font-size:12px;pointer-events:none}
#msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px}
button,select{font:inherit}
#sec{position:absolute;inset:0;overflow:auto;display:none;padding:8px;gap:14px;align-content:start;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr))}
body.v2d #sec{display:grid}body.v2d canvas#c,body.v2d .tag,body.v2d #legend,body.v2d .d3{display:none!important}
#sec .nm{font-weight:600;margin-bottom:4px}#sec .pn{display:flex;gap:8px}#sec .p{flex:1 1 0;min-width:0}
#sec canvas{width:100%;height:auto;display:block;background:#000;border-radius:4px;cursor:default}#sec input{width:100%;margin:2px 0}#sec .lb{font-size:12px;opacity:.75}
</style></head><body>
<div id="bar">
 <label>show <select id="vm"><option value="3d">3D</option><option value="sec">sections x/y/z</option><option value="proj">projections x/y/z</option></select></label>
 <label class="d3" title="off: every map starts at its own level so none is empty; on: one level in real units for all maps"><input id="same" type="checkbox"> same level</label>
 <label class="d3">level <input id="lvl" type="range" min="0" max="255" value="128"><span id="lvlv"></span></label>
 <label class="d3">cut <input id="cut" type="range" min="-100" max="100" value="100"></label>
 <label>detail <select id="det"><option>64</option><option selected>128</option><option>192</option><option>256</option></select></label>
 <label id="modewrap" hidden>view <select id="mode2"><option value="side">side by side</option><option value="diff">difference A&minus;B</option></select></label>
 <label id="maskwrap" hidden><input id="maskon" type="checkbox" checked> mask</label>
 <label class="d3"><input id="dust" type="checkbox" checked> hide dust</label>
 <label class="d3"><input id="smooth" type="checkbox"> smooth</label>
 <label class="d3">light <select id="lit"><option value="simple">simple</option><option value="soft">soft</option></select></label>
 <label class="d3">style <select id="sty"><option value="default">default</option><option value="paper">paper (white)</option><option value="clay">clay</option><option value="depth">depth</option></select></label>
 <label class="d3"><input id="wb" type="checkbox"> white background</label>
 <button id="reset">reset view</button><button id="png">save PNG</button>
 <span id="info"></span><span id="mode" style="opacity:.7"></span>
</div>
<div id="stage"><canvas id="c"></canvas><div id="sec"></div><div id="msg">loading&hellip;</div>
 <div id="legend"><b id="legt"></b><i></i><span><span id="leg0"></span><span id="leg1"></span></span></div></div>
<script>
const JOB = __JOB__, FILES = __FILES__, TOKEN = __TOKEN__, MASK = __MASK__, COLOR = __COLOR__, RENDER_DEFAULT = __RENDER__;
const QS = new URLSearchParams(location.search), num = k => { const v = parseFloat(QS.get(k)); return isFinite(v) ? v : null; };
const ref = s => { const i = s.indexOf(":"); return i < 0 ? {job: JOB, f: s} : {job: s.slice(0, i), f: s.slice(i + 1)}; };
const CHROME = QS.get("chrome") === "1"; if (CHROME) document.body.classList.add("chrome");
const status = s => { if (CHROME) fetch("/view3d-state?t=" + encodeURIComponent(TOKEN) + "&s=" + encodeURIComponent(s)).catch(() => {}); };
const $ = id => document.getElementById(id);
const cv = $("c"), msg = $("msg");
const gl = cv.getContext("webgl2", {preserveDrawingBuffer: true, antialias: true});
if (!gl) { msg.textContent = "WebGL2 is not available in this browser. Use the ChimeraX buttons instead."; status("nogl"); throw 0; }

// GPU or not: this runs in the viewer's own browser (laptop, workstation), never on the head node, which only serves bytes.
// A software renderer (SwiftShader, llvmpipe, ...) still works but is slow: start at detail 64 and draw at half resolution.
const dbg = gl.getExtension("WEBGL_debug_renderer_info");
const GPU = dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : "unknown";
const RMODE = QS.get("render") || RENDER_DEFAULT;     // gpu | soft | auto (auto = detect)
const SOFT = RMODE === "soft" || (RMODE !== "gpu" && /swiftshader|llvmpipe|software|basic render|softpipe/i.test(GPU));
const SCALE = SOFT && !CHROME ? 0.5 : 1;               // a screenshot is taken at full resolution even when slow
if (SOFT) $("det").value = "64";
if (QS.get("detail")) $("det").value = String(Math.min(256, Math.max(32, parseInt(QS.get("detail"), 10) || 128)));
$("mode").textContent = (SOFT ? "software rendering (no GPU found): reduced quality \u2013 " : "GPU: ") + GPU;

const VS = `#version 300 es
in vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`;
const FS = `#version 300 es
precision highp float; precision highp sampler3D;
uniform sampler3D vol, volB, msk, col; uniform mat3 R; uniform vec3 ext; uniform float level, zoom, clipZ, dt, texel;
uniform vec2 res, org; uniform vec3 bg;
uniform int mode;                       // 0 = surface of vol, 1 = surface of |vol - volB| (real units)
uniform vec2 loA, scA, loB, scB;        // x = lo, y unused / scale = hi - lo, per map (real units from the 8-bit value)
uniform vec3 surf; uniform int sty; uniform vec2 light;
uniform float dmax, mlevel, cmin, cmax, clo, cscale; uniform bool useMask, useCol;
out vec4 o;
const float D = 3.0;
float sdiff(vec3 c){ return (loA.x + texture(vol, c).r * scA.x) - (loB.x + texture(volB, c).r * scB.x); }
float dens(vec3 p){ vec3 c = p / ext + 0.5; return mode == 1 ? abs(sdiff(c)) : texture(vol, c).r; }
vec3 ramp(float f){ f = clamp(f, 0., 1.);       // blue -> cyan -> yellow -> red (low -> high)
  vec3 a = vec3(0.17,0.31,0.85), b = vec3(0.15,0.72,0.83), c = vec3(0.94,0.89,0.26), d = vec3(0.85,0.22,0.17);
  return f < 0.33 ? mix(a, b, f / 0.33) : f < 0.66 ? mix(b, c, (f - 0.33) / 0.33) : mix(c, d, (f - 0.66) / 0.34); }
vec3 mnormal(vec3 p){ vec3 e = vec3(texel) * ext, c = p / ext + 0.5;
  return normalize(vec3(texture(msk, c + vec3(e.x,0,0)/ext).r - texture(msk, c - vec3(e.x,0,0)/ext).r,
                        texture(msk, c + vec3(0,e.y,0)/ext).r - texture(msk, c - vec3(0,e.y,0)/ext).r,
                        texture(msk, c + vec3(0,0,e.z)/ext).r - texture(msk, c - vec3(0,0,e.z)/ext).r) + 1e-6); }
void main(){
  vec2 q = (gl_FragCoord.xy - org - 0.5 * res) / min(res.x, res.y) * 2.0 / zoom;
  vec3 om = vec3(q, D) * R, dm = vec3(0., 0., -1.) * R;          // view -> model (R is model -> view)
  vec3 h = ext * 0.5, a = (-h - om) / dm, b = (h - om) / dm;      // slab test against the box
  vec3 lo = min(a, b), hi = max(a, b);
  float t0 = max(max(lo.x, lo.y), lo.z), t1 = min(min(hi.x, hi.y), hi.z);
  if (t1 <= t0) { o = vec4(bg, 1.); return; }
  float tc = D - clipZ; bool cut = tc > t0; t0 = max(t0, tc);
  float t = t0; bool hit = false; float v = 0.; float tm = -1.;
  for (int i = 0; i < 700; i++) {
    if (t > t1) break;
    vec3 pp = om + dm * t;
    if (useMask && tm < 0. && texture(msk, pp / ext + 0.5).r >= mlevel) tm = t;   // first crossing of the mask surface
    v = dens(pp);
    if (v >= level) { hit = true; break; }
    t += dt;
  }
  vec3 base = bg; float alpha = 0.;
  if (hit) {
  if (cut && t <= t0 + dt) { base = vec3(0.25 + 0.75 * (mode == 1 ? v / dmax : v)); alpha = 2.; }   // cut face: grey density
  else {
  float ta = t - dt, tb = t;
  for (int i = 0; i < 6; i++) { float m = 0.5 * (ta + tb); if (dens(om + dm * m) >= level) tb = m; else ta = m; }
  vec3 p = om + dm * tb, e = vec3(texel) * ext;
  vec3 g = vec3(dens(p + vec3(e.x,0,0)) - dens(p - vec3(e.x,0,0)),
                dens(p + vec3(0,e.y,0)) - dens(p - vec3(0,e.y,0)),
                dens(p + vec3(0,0,e.z)) - dens(p - vec3(0,0,e.z)));
  vec3 n = R * (-normalize(g + 1e-6));                               // outward, in view space
  vec3 L = normalize(vec3(-0.4, 0.5, 0.8));
  float diff = max(dot(n, L), 0.) * 0.6 + max(n.z, 0.) * 0.3;
  float spec = pow(max(dot(reflect(-L, n), vec3(0., 0., 1.)), 0.), 24.) * 0.25;
  vec3 sc = sty == 3 ? mix(vec3(0.95, 0.55, 0.20), vec3(0.20, 0.45, 0.90), clamp((tb - t0) / max(t1 - t0, 1e-4), 0., 1.)) : surf;
  if (mode == 1) sc = sdiff(p / ext + 0.5) >= 0. ? vec3(0.93, 0.50, 0.12) : vec3(0.20, 0.45, 0.90);   // A > B orange, B > A blue
  else if (useCol) sc = ramp((clo + texture(col, p / ext + 0.5).r * cscale - cmin) / max(cmax - cmin, 1e-6));
  base = sc * (light.x + diff * light.y) + spec * light.y; alpha = 2.;
  }}
  if (useMask && tm >= 0. && (!hit || tm < t)) {                      // see-through shell over whatever lies behind it
    vec3 nm = R * (-mnormal(om + dm * tm)); float sh = 0.45 + 0.55 * max(dot(nm, normalize(vec3(-0.4, 0.5, 0.8))), 0.);
    base = mix(base, vec3(0.75, 0.75, 0.78) * sh, 0.30);
  }
  o = vec4(base, 1.);
}`;
function sh(type, src){ const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { msg.textContent = gl.getShaderInfoLog(s); throw 0; } return s; }
const pr = gl.createProgram(); gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS));
gl.linkProgram(pr); gl.useProgram(pr);
const U = n => gl.getUniformLocation(pr, n);
gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

let maps = [], mask = null, colmap = null, R = ident(), R0 = ident(), zoom = 2.9, dirty = true, diffOK = false;
function ident(){ return [1,0,0, 0,1,0, 0,0,1]; }
function mul(a, b){ const r = []; for (let c = 0; c < 3; c++) for (let rr = 0; rr < 3; rr++)   // column-major a*b
  r[c*3+rr] = a[rr]*b[c*3] + a[3+rr]*b[c*3+1] + a[6+rr]*b[c*3+2]; return r; }
function rot(axis, ang){ const c = Math.cos(ang), s = Math.sin(ang);
  return axis === "y" ? [c,0,-s, 0,1,0, s,0,c] : [1,0,0, 0,c,s, 0,-s,c]; }
const rad = d => d * Math.PI / 180;
R0 = mul(rot("x", rad(num("rx") || 0)), rot("y", rad(num("ry") || 0))); R = R0;

function fetchCube(r, detail){
  return fetch("/volume?t=" + encodeURIComponent(TOKEN) + "&job=" + encodeURIComponent(r.job) +
      "&f=" + encodeURIComponent(r.f) + "&detail=" + detail).then(x => x.ok ? x.arrayBuffer() : x.json().then(j => Promise.reject(j.error || x.status)));
}
function makeMap(b, name, unit){
  const dv = new DataView(b), nx = dv.getUint16(0, true), ny = dv.getUint16(2, true), nz = dv.getUint16(4, true);
  const lo = dv.getFloat32(8, true), hi = dv.getFloat32(12, true), apix = dv.getFloat32(16, true);
  const data = new Uint8Array(b, 20, nx * ny * nz);
  const tex = gl.createTexture(); gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_3D, tex);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, nx, ny, nz, 0, gl.RED, gl.UNSIGNED_BYTE, data);
  for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
    [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_3D, k, v);
  const m = Math.max(nx, ny, nz), hist = new Uint32Array(256); for (let j = 0; j < data.length; j++) hist[data[j]]++;
  return {name, tex, unit, data, n: [nx, ny, nz], m, lo, hi, apix, hist, len: data.length};
}
function load(detail){
  msg.style.display = "flex"; msg.textContent = "loading…";
  const refs = FILES.map(ref), extra = [MASK, COLOR].map(x => x ? ref(x) : null);
  Promise.all([...refs, ...extra.filter(Boolean)].map(r => fetchCube(r, detail))).then(bufs => {
    [maps, mask, colmap].forEach(x => { (Array.isArray(x) ? x : [x]).forEach(m => m && gl.deleteTexture(m.tex)); });
    const mixed = refs.some(r => r.job !== refs[0].job), nm = r => mixed ? r.job.split("/").pop() + ":" + r.f : r.f;
    maps = refs.map((r, i) => makeMap(bufs[i], nm(r), i === 1 ? 1 : 0));          // units 0 = vol, 1 = volB, 2 = mask, 3 = colour
    let k = refs.length;
    mask = extra[0] ? makeMap(bufs[k++], MASK, 2) : null;
    colmap = extra[1] ? makeMap(bufs[k++], COLOR, 3) : null;
    // unit 1 must always hold a texture when a 2nd map exists; with one map the unused samplers just alias unit 0
    diffOK = maps.length === 2 && maps[0].n.every((v, i) => v === maps[1].n[i]);
    $("modewrap").hidden = maps.length !== 2; $("maskwrap").hidden = !mask;
    if (maps.length === 2 && !diffOK) $("modewrap").title = "difference needs maps with the same box and voxel count";
    if (QS.get("mode") === "diff" && maps.length === 2) $("mode2").value = "diff";
    setupLevel();
    const lg = $("legend");
    if (colmap) {   // legend range: the 2nd..98th percentile of the non-zero voxels of the colour map
      const h = colmap.hist, skip = colmap.lo <= 0 ? 1 : 0; let tot = 0; for (let i = skip; i < 256; i++) tot += h[i];
      let a = skip, s = 0, b = 255; for (; a < 255; a++) { s += h[a]; if (s >= 0.02 * tot) break; }
      s = 0; for (; b > a; b--) { s += h[b]; if (s >= 0.02 * tot) break; }
      const v = i => colmap.lo + i / 255 * (colmap.hi - colmap.lo);
      colmap.cmin = v(a); colmap.cmax = v(b);
      lg.style.display = "block"; $("legt").textContent = colmap.name; $("leg0").textContent = colmap.cmin.toFixed(1); $("leg1").textContent = colmap.cmax.toFixed(1);
    } else lg.style.display = "none";
    msg.style.display = "none"; labels(); dirty = true; setVM(); applyDust();
    $("info").textContent = maps[0].n.join("×") + " voxels, " + maps[0].apix.toFixed(2) + " Å/voxel (detail " + detail + ")";
  }).catch(e => { msg.textContent = "could not load the map: " + e; status("failed " + e); });
}
const isDiff = () => $("mode2").value === "diff" && maps.length === 2;
function diffMax(){ const a = maps[0], b = maps[1]; return Math.max(Math.abs(a.hi - b.lo), Math.abs(b.hi - a.lo)); }
// slider 0..255; side by side: byte level of map 1 (shown in real units); difference: 0..max|A-B| in real units
function setupLevel(){
  if (isDiff()) { $("lvl").value = 64; return; }
  const q = QS.get("level"), m = maps[0];
  const auto = x => { let s = 0, v = 255, bg = 0; for (let u = 1; u < 256; u++) if (x.hist[u] > x.hist[bg]) bg = u;
    for (; v > 1; v--) { s += x.hist[v]; if (s >= 0.01 * x.len) break; }
    return v <= bg + 2 ? Math.round(bg + 0.3 * (255 - bg)) : v; };   // 1 % rule; a map whose top 1 % is all background level gets a level above the background instead
  maps.forEach(x => { x.k = auto(x) / auto(m); });   // every map keeps its own start level relative to the slider
  if (q !== null && q !== "auto" && isFinite(parseFloat(q))) { $("same").checked = true; $("lvl").value = Math.round(Math.min(255, Math.max(0, (parseFloat(q) - m.lo) / (m.hi - m.lo) * 255))); return; }
  // start level: the value that leaves ~2 % of the first map's voxels above it; the user moves it from there
  $("lvl").value = auto(m);
}
// byte level of one map: its own start level scaled by the slider, or the same real-unit level for all ("same level")
function mapByte(m){ const v = +$("lvl").value; if (isDiff() || maps.length < 2) return v;
  return $("same").checked ? Math.min(255, Math.max(0, Math.round((realLevel() - m.lo) / (m.hi - m.lo) * 255))) : Math.min(255, Math.max(1, Math.round(v * (m.k || 1)))); }
const PAL = [[0.31,0.47,0.65],[0.95,0.56,0.17],[0.35,0.62,0.31],[0.88,0.34,0.35],[0.46,0.72,0.70],[0.93,0.79,0.28],[0.69,0.48,0.63],[0.61,0.46,0.37]];   // same order as the class cards
function mapRGB(m, i, base){ if (isDiff() || maps.length < 2 || $("sty").value === "paper" || $("sty").value === "clay" || $("sty").value === "depth") return base;
  const c = /class0*([0-9]+)/.exec(m.name); return PAL[((c ? +c[1] : i + 1) - 1) % 8]; }
function realLevel(){ if (isDiff()) return $("lvl").value / 255 * diffMax(); const m = maps[0]; return m.lo + $("lvl").value / 255 * (m.hi - m.lo); }
// columns that give the biggest square-ish tile for n maps in the stage (narrow panel: stacked, wide window: side by side)
function gridCols(n){ const w = $("stage").clientWidth || 1, h = $("stage").clientHeight || 1; let best = 1, bs = 0;
  for (let c = 1; c <= n; c++) { const t = Math.min(w / c, h / Math.ceil(n / c)); if (t > bs) { bs = t; best = c; } } return best; }
function labels(){ document.querySelectorAll(".tag").forEach(e => e.remove());
  const names = isDiff() ? [maps[0].name + " − " + maps[1].name + "  (orange: A higher, blue: B higher)"] : maps.map(m => m.name);
  const cols = gridCols(names.length), rows = Math.ceil(names.length / cols);
  names.forEach((nm, i) => { const d = document.createElement("div"); d.className = "tag"; d.textContent = nm; if (!isDiff() && maps.length > 1) d.style.borderLeft = "5px solid rgb(" + mapRGB(maps[i], i, [0,0,0]).map(v => Math.round(v * 255)).join(",") + ")";
    d.style.left = (i % cols) / cols * 100 + 1 + "%"; d.style.top = Math.floor(i / cols) / rows * 100 + 1 + "%"; $("stage").appendChild(d); }); }

// 2D views from the 8-bit cube already in the browser: three orthogonal sections (slider each) or mean projections, per map.
let VM = ["sec", "proj"].includes(QS.get("vm")) ? QS.get("vm") : "3d";
function pct(h, len, q){ let s = 0; for (let v = 0; v < 256; v++) { s += h[v]; if (s >= q * len) return v; } return 255; }
function paint(c, w, h, get, lo, hi){
  c.width = w; c.height = h; const g = c.getContext("2d"), im = g.createImageData(w, h), k = 255 / Math.max(hi - lo, 1e-6);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const v = Math.max(0, Math.min(255, (get(x, y) - lo) * k)), o = (y * w + x) * 4;
    im.data[o] = im.data[o + 1] = im.data[o + 2] = v; im.data[o + 3] = 255; }
  g.putImageData(im, 0, 0);
}
function renderSec(){
  const box = $("sec"); box.innerHTML = ""; if (VM === "3d" || !maps.length) return;
  maps.forEach(m => {
    const [nx, ny, nz] = m.n, d = m.data, at = (x, y, z) => d[x + nx * (y + ny * z)];
    const lo = pct(m.hist, m.len, 0.01), hi = Math.max(lo + 1, pct(m.hist, m.len, 0.998));
    const blk = document.createElement("div"); blk.innerHTML = "<div class=nm></div><div class=pn></div>";
    blk.firstChild.textContent = m.name + "  (" + m.apix.toFixed(1) + " Å/voxel, " + (VM === "sec" ? "sections" : "mean projections") + ")";
    [{t: "XY, z", w: nx, h: ny, n: nz, get: (u, v, a) => at(u, v, a)}, {t: "XZ, y", w: nx, h: nz, n: ny, get: (u, v, a) => at(u, a, v)},
     {t: "YZ, x", w: ny, h: nz, n: nx, get: (u, v, a) => at(a, u, v)}].forEach(ax => {
      const p = document.createElement("div"); p.className = "p"; p.innerHTML = "<div class=lb></div><canvas></canvas>";
      const c = p.querySelector("canvas"), lb = p.firstChild;
      if (VM === "proj") {
        const f = new Float32Array(ax.w * ax.h); let a0 = 1e9, a1 = -1e9;
        for (let v = 0; v < ax.h; v++) for (let u = 0; u < ax.w; u++) { let s = 0; for (let a = 0; a < ax.n; a++) s += ax.get(u, v, a); s /= ax.n; f[v * ax.w + u] = s; a0 = Math.min(a0, s); a1 = Math.max(a1, s); }
        lb.textContent = ax.t[0] + ax.t[1] + " projection along " + ax.t.slice(-1);
        paint(c, ax.w, ax.h, (u, v) => f[v * ax.w + u], a0, a1);
      } else {
        const sl = document.createElement("input"); sl.type = "range"; sl.min = 0; sl.max = ax.n - 1; sl.value = Math.floor(ax.n / 2); p.appendChild(sl);
        const go = () => { lb.textContent = ax.t + " = " + sl.value + " / " + (ax.n - 1); paint(c, ax.w, ax.h, (u, v) => ax.get(u, v, +sl.value), lo, hi); };
        sl.oninput = go; go();
      }
      blk.lastChild.appendChild(p);
    });
    box.appendChild(blk);
  });
}
function setVM(){ VM = $("vm").value; document.body.classList.toggle("v2d", VM !== "3d"); renderSec(); dirty = true; }
$("vm").value = VM; $("vm").onchange = setVM;
if (["paper", "clay", "depth"].includes(QS.get("style"))) $("sty").value = QS.get("style");
// "hide dust": drop connected regions above the level that are smaller than 5 % of the biggest one (re-uploaded to the GPU texture)
function dustFilter(m, lb, d){
  const nx = m.n[0], ny = m.n[1], N = d.length, seen = new Uint8Array(N), stack = new Int32Array(N), order = new Int32Array(N), regions = [];
  let oc = 0, best = 0;
  for (let s0 = 0; s0 < N; s0++) {
    if (seen[s0] || d[s0] < lb) continue;
    let sp = 0; const st = oc; stack[sp++] = s0; seen[s0] = 1;
    while (sp) {
      const i = stack[--sp]; order[oc++] = i;
      const x = i % nx, y = ((i / nx) | 0) % ny, z = (i / (nx * ny)) | 0;
      for (const j of [x > 0 ? i - 1 : -1, x < nx - 1 ? i + 1 : -1, y > 0 ? i - nx : -1, y < ny - 1 ? i + nx : -1, z > 0 ? i - nx * ny : -1, z < m.n[2] - 1 ? i + nx * ny : -1])
        if (j >= 0 && !seen[j] && d[j] >= lb) { seen[j] = 1; stack[sp++] = j; }
    }
    regions.push([st, oc - st]); if (oc - st > best) best = oc - st;
  }
  const out = d.slice();
  for (const [st, len] of regions) if (len < 0.05 * best) for (let k = st; k < st + len; k++) out[order[k]] = 0;
  return out;
}
// [1 2 1]/4 along each axis: calms the noise of a low-resolution map without moving its surface much
function blur(m){
  let a = m.data; const [nx, ny, nz] = m.n;
  for (const [st, n] of [[1, nx], [nx, ny], [nx * ny, nz]]) {
    const o = new Uint8Array(a.length);
    for (let i = 0; i < a.length; i++) { const c = ((i / st) | 0) % n; o[i] = ((c > 0 ? a[i - st] : a[i]) + 2 * a[i] + (c < n - 1 ? a[i + st] : a[i]) + 2) >> 2; }
    a = o;
  }
  return a;
}
let dustTimer = 0;
function applyDust(){
  if (!maps.length) return;
  const on = $("dust").checked && !isDiff(), sm = $("smooth").checked && !isDiff(), L = realLevel();
  maps.forEach(m => {
    const lb = on ? Math.max(1, mapByte(m)) : -1, key = lb + (sm ? 1000 : 0);
    if (m.dustKey === key) return; m.dustKey = key;
    const src = sm ? (m.sm || (m.sm = blur(m))) : m.data;
    gl.activeTexture(gl.TEXTURE0 + m.unit); gl.bindTexture(gl.TEXTURE_3D, m.tex); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texSubImage3D(gl.TEXTURE_3D, 0, 0, 0, 0, m.n[0], m.n[1], m.n[2], gl.RED, gl.UNSIGNED_BYTE, on ? dustFilter(m, lb, src) : src);
  });
  dirty = true;
}
const dustSoon = () => { clearTimeout(dustTimer); dustTimer = setTimeout(applyDust, 150); };
$("same").onchange = applyDust; $("dust").onchange = applyDust; $("smooth").onchange = applyDust; $("lvl").addEventListener("input", dustSoon); $("mode2").addEventListener("change", applyDust);
function draw(){
  dirty = false;
  const dpr = (devicePixelRatio || 1) * SCALE, W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr);
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const STY = {default: [0.30, 0.55, 0.85], paper: [0.50, 0.58, 0.70], clay: [0.80, 0.72, 0.62], depth: [0.30, 0.55, 0.85]}, sty = $("sty").value;
  const bg = $("wb").checked || sty === "paper" ? [1, 1, 1] : [0.08, 0.09, 0.11];
  gl.viewport(0, 0, W, H); gl.clearColor(bg[0], bg[1], bg[2], 1); gl.clear(gl.COLOR_BUFFER_BIT);
  if (!maps.length) return;
  const diff = isDiff();
  if (diff && !diffOK) { msg.style.display = "flex"; msg.textContent = "Difference needs two maps with the same box size and voxel count (here " +
    maps[0].n.join("×") + " vs " + maps[1].n.join("×") + "). Re-extract one on the other's grid, or use side by side."; return; }
  if (msg.style.display === "flex" && msg.textContent.startsWith("Difference")) msg.style.display = "none";
  const L = realLevel(), shown = diff ? 1 : maps.length, cols = gridCols(shown), rows = Math.ceil(shown / cols);
  const tw = Math.floor(W / cols), th = Math.floor(H / rows);
  // textures: unit 0 = vol (this tile), 1 = volB (difference only), 2 = mask, 3 = colour map. Unused samplers alias a bound texture.
  for (let i = 0; i < 4; i++) { gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_3D, (i === 1 ? (diff ? maps[1] : maps[0]) : i === 2 ? (mask || maps[0]) : i === 3 ? (colmap || maps[0]) : maps[0]).tex); }
  gl.uniform1i(U("vol"), 0); gl.uniform1i(U("volB"), 1); gl.uniform1i(U("msk"), 2); gl.uniform1i(U("col"), 3);
  gl.uniform1i(U("mode"), diff ? 1 : 0); gl.uniform3fv(U("surf"), STY[sty]); gl.uniform2fv(U("light"), $("lit").value === "soft" ? [0.55, 0.55] : [0.18, 1.0]); gl.uniform1i(U("sty"), sty === "depth" ? 3 : 0);
  gl.uniform1i(U("useMask"), mask && $("maskon").checked ? 1 : 0); gl.uniform1i(U("useCol"), colmap && !diff ? 1 : 0);
  if (mask) gl.uniform1f(U("mlevel"), Math.min(1, Math.max(0, (0.5 - mask.lo) / (mask.hi - mask.lo))));
  if (colmap) { gl.uniform1f(U("cmin"), colmap.cmin); gl.uniform1f(U("cmax"), colmap.cmax); gl.uniform1f(U("clo"), colmap.lo); gl.uniform1f(U("cscale"), colmap.hi - colmap.lo); }
  if (diff) { gl.uniform1f(U("dmax"), diffMax());
    gl.uniform2f(U("loA"), maps[0].lo, 0); gl.uniform2f(U("scA"), maps[0].hi - maps[0].lo, 0);
    gl.uniform2f(U("loB"), maps[1].lo, 0); gl.uniform2f(U("scB"), maps[1].hi - maps[1].lo, 0); }
  for (let i = 0; i < shown; i++) {
    const m = maps[i], x = (i % cols) * tw, y = H - (Math.floor(i / cols) + 1) * th;
    gl.viewport(x, y, tw, th); gl.enable(gl.SCISSOR_TEST); gl.scissor(x, y, tw, th);
    if (!diff) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_3D, m.tex); }
    gl.uniform1f(U("level"), diff ? L : mapByte(m) / 255);
    gl.uniform3fv(U("surf"), mapRGB(m, i, STY[sty]));
    gl.uniformMatrix3fv(U("R"), false, R);
    gl.uniform3f(U("ext"), m.n[0] / m.m, m.n[1] / m.m, m.n[2] / m.m);
    gl.uniform1f(U("zoom"), zoom); gl.uniform1f(U("clipZ"), +$("cut").value / 100 * 0.9);
    gl.uniform1f(U("dt"), 1 / m.m * 0.7); gl.uniform1f(U("texel"), 1 / m.m);
    gl.uniform2f(U("res"), tw, th); gl.uniform2f(U("org"), x, y); gl.uniform3f(U("bg"), bg[0], bg[1], bg[2]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  gl.disable(gl.SCISSOR_TEST);
  $("lvlv").textContent = L.toPrecision(3) + (diff ? " (|A−B|)" : "");
  if (!document.body.dataset.drawn) { document.body.dataset.drawn = "1"; status("ready " + (SOFT ? "soft" : "gpu") + " " + GPU); }
}
(function loop(){ if (dirty) draw(); requestAnimationFrame(loop); })();
const redraw = () => { dirty = true; };
["lvl", "cut", "wb", "maskon", "sty", "lit", "same"].forEach(id => $(id).addEventListener("input", redraw));
$("mode2").addEventListener("change", () => { setupLevel(); labels(); redraw(); });
$("det").addEventListener("change", () => load($("det").value));
$("reset").onclick = () => { R = R0; zoom = 2.9; $("cut").value = 100; redraw(); };
$("png").onclick = () => { draw(); cv.toBlob(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b);
  a.download = (FILES.length === 1 ? FILES[0].replace(/\\.[^.]+$/, "") : "maps") + ".png"; a.click(); URL.revokeObjectURL(a.href); }); };
let drag = null;
cv.addEventListener("pointerdown", e => { drag = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId); cv.style.cursor = "grabbing"; });
cv.addEventListener("pointerup", () => { drag = null; cv.style.cursor = "grab"; });
cv.addEventListener("pointermove", e => { if (!drag) return;
  R = mul(mul(rot("x", (e.clientY - drag[1]) * 0.01), rot("y", (e.clientX - drag[0]) * 0.01)), R);   // turn about the view axes
  drag = [e.clientX, e.clientY]; redraw(); });
cv.addEventListener("wheel", e => { e.preventDefault(); zoom = Math.min(8, Math.max(0.4, zoom * Math.exp(-e.deltaY * 0.001))); redraw(); }, {passive: false});
cv.addEventListener("dblclick", () => $("reset").click());
addEventListener("resize", redraw);
load($("det").value);
</script></body></html>
"""


def render_view3d(job, files, token, mask=None, color=None, render="auto"):
    """Page for the maps `files` ('name' in `job`, or 'other/job001:name'); optional mask / colour map refs. Values are embedded as
    JSON; `<` is escaped so no value can end the script."""
    def js(v):
        return json.dumps(v).replace("<", "\\u003c")
    return (_PAGE.replace("__JOB__", js(job)).replace("__FILES__", js(files)).replace("__TOKEN__", js(token))
            .replace("__MASK__", js(mask)).replace("__COLOR__", js(color)).replace("__RENDER__", js(render if render in ("auto", "gpu", "soft") else "auto")))
