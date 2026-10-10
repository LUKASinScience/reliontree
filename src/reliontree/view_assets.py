"""CSS + JS for the pan/zoom viewport and the path picker in the HTML page.
Plain strings (not format templates), so braces are single."""

VIEW_CSS = """
  #main { flex: 1; min-width: 0; display: flex; flex-direction: column; height: 100vh; overflow: hidden; padding: 16px 20px; }
  #main > * { flex: none; }
  #treeView { flex: 1 1 auto; min-height: 0; overflow: hidden; padding: 0; position: relative;
              border: 1px solid var(--border); border-radius: 8px; background: #fff; }
  #treeView svg { display: block; width: 100%; height: 100%; cursor: grab; user-select: none; }
  #treeView svg.panning { cursor: grabbing; }
  #tableView { flex: 1 1 auto; min-height: 0; overflow: auto; }
  #toolbar { align-items: center; }
  #pathBar, #zoomBar { display: inline-flex; align-items: center; gap: 4px; padding: 0 8px; border-left: 1px solid var(--border); }
  #pathBar .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted); margin-right: 2px; }
  .pchip { font-size: 12px; border-radius: 999px; padding: 2px 4px 2px 10px; color: #fff; cursor: default; white-space: nowrap; }
  .pchip button { all: unset; cursor: pointer; padding: 0 6px; font-weight: bold; }
  .pchip-a { background: #1565c0; } .pchip-b { background: #e65100; }
  #toolbar button.on { background: var(--accent-bg); border-color: var(--accent); }
  #pathPanel { max-height: 24vh; overflow: auto; margin: 0 0 10px; font-size: 12px; border: 1px solid var(--border);
               border-radius: 8px; padding: 8px 12px; background: var(--surface); }
  #pathPanel[hidden] { display: none; }
  #pathPanel table { width: 100%; table-layout: fixed; border-collapse: collapse; }
  #pathPanel th { text-align: left; font-size: 11px; padding: 2px 8px; }
  #pathPanel td { padding: 3px 8px; vertical-align: top; border-bottom: 1px solid var(--border); }
  #pathPanel th.a, #pathPanel td.a { border-left: 3px solid #1565c0; }
  #pathPanel th.b, #pathPanel td.b { border-left: 3px solid #e65100; }
  #pathPanel .ptoggle { cursor: pointer; user-select: none; }
  #pathPanel .sub { color: var(--text-muted); }
  #pathPanel .chg { font-family: ui-monospace, monospace; font-size: 11px; }
  .job-item .pick { flex: none; font-size: 10px; font-weight: bold; padding: 0 5px; border-radius: 4px; background: var(--surface); cursor: pointer; }
  .job-item .pick-a { border: 1px solid #1565c0; color: #1565c0; } .job-item .pick-b { border: 1px solid #e65100; color: #e65100; }
  .job-item .pick:hover { color: #fff; } .job-item .pick-a:hover { background: #1565c0; } .job-item .pick-b:hover { background: #e65100; }
  .job-item .job-label { flex: 1 1 40px; }
  .flag { font-size: 11px; } .lvl-bad { color: #c62828; } .lvl-warn { color: #e65100; } .lvl-info { color: #546e7a; } .lvl-good { color: #2e7d32; }
  .lvl-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: currentColor; }
  .exp-badge { font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-bg); border-radius: 999px; padding: 2px 10px; margin-left: 8px; vertical-align: middle; }
  .missing-toggle { padding: 6px 12px; font-size: 11px; color: var(--text-muted); cursor: pointer; border-bottom: 1px solid var(--border); }
  .missing-toggle:hover { background: var(--neutral-bg); }
  .job-item.offpath { opacity: 0.55; }
  #pathPick { max-width: 150px; }
  .drawer .pathbtns { display: flex; gap: 6px; margin: 0 0 10px; }
  .drawer .pathbtns button { font-size: 12px; }
  .drawer .pathbtns .pa-btn { border-color: #1565c0; color: #1565c0; }
  .drawer .pathbtns .pb-btn { border-color: #e65100; color: #e65100; }
  svg .mask-chip { cursor: pointer; }
  svg .mask-chip:hover rect { stroke: #7cb342; }
  svg .outline { pointer-events: none; }
  .seg { display: inline-flex; } .seg button { border-radius: 0; } .seg button:first-child { border-radius: 6px 0 0 6px; }
  .seg button:last-child { border-radius: 0 6px 6px 0; margin-left: -1px; } .seg button:disabled { opacity: .45; cursor: default; }
  svg.pathmode .job-card:not(.pa):not(.pb):not(.pab), svg.pathmode .edge:not(.pa):not(.pb):not(.pab) { opacity: 0.55; }
  svg .pa > .outline { stroke: #1565c0; stroke-width: 4; }
  svg .pb > .outline { stroke: #e65100; stroke-width: 4; }
  svg .pab > .outline { stroke: #7b1fa2; stroke-width: 4; }
  svg .edge.pa { stroke: #1565c0; stroke-width: 3; stroke-dasharray: none; marker-end: url(#arr-main); }
  svg .edge.pb { stroke: #e65100; stroke-width: 3; stroke-dasharray: none; marker-end: url(#arr-b); }
  svg .edge.pab { stroke: #7b1fa2; stroke-width: 3; stroke-dasharray: none; marker-end: url(#arr-ab); }
"""

VIEW_JS = """
// ---------- viewport: pan / zoom, limited to the content ----------
// Wheel / trackpad scroll pans, ctrl+wheel (or pinch) zooms, drag pans. You cannot scroll past the tree.
const svgEl = document.querySelector("#treeView svg");
const SVG_W = +svgEl.dataset.w, SVG_H = +svgEl.dataset.h;
let content = {w: SVG_W, h: SVG_H};          // size of what is currently drawn (smaller in path view)
const view = {x: -30, y: -30, scale: 1};
const EDGE_PAD = 30;
let dragged = false;
function viewSize() { const r = svgEl.getBoundingClientRect(); return {w: r.width || 1, h: r.height || 1}; }
function overviewScale() {
  const s = viewSize();
  return Math.min(s.w / (content.w + 2 * EDGE_PAD), s.h / (content.h + 2 * EDGE_PAD), 1);
}
function clampView() {
  const s = viewSize(), vw = s.w / view.scale, vh = s.h / view.scale;
  view.scale = Math.min(3, Math.max(overviewScale(), view.scale));
  const w = s.w / view.scale, h = s.h / view.scale;
  view.x = content.w + 2 * EDGE_PAD <= w ? (content.w - w) / 2 : Math.min(Math.max(view.x, -EDGE_PAD), content.w + EDGE_PAD - w);
  view.y = content.h + 2 * EDGE_PAD <= h ? -EDGE_PAD : Math.min(Math.max(view.y, -EDGE_PAD), content.h + EDGE_PAD - h);
}
function applyView() {
  if (!svgEl.getBoundingClientRect().width) return;  // tree view hidden (table view)
  clampView();
  const s = viewSize();
  svgEl.setAttribute("viewBox", [view.x, view.y, s.w / view.scale, s.h / view.scale].join(" "));
  try { sessionStorage.setItem("reliontree.vp", JSON.stringify(view)); } catch (e) {}
}
function zoomAt(f, cx, cy) {
  const s = viewSize();
  if (cx === undefined) { cx = s.w / 2; cy = s.h / 2; }
  const mx = view.x + cx / view.scale, my = view.y + cy / view.scale;
  view.scale = Math.min(3, Math.max(overviewScale(), view.scale * f));
  view.x = mx - cx / view.scale; view.y = my - cy / view.scale;
  applyView();
}
function zoomBy(f) { zoomAt(f); }
// 100%: cards at actual size, back to the top-left. Overview: the whole content in one screen.
function actualSize() { view.scale = 1; view.x = -EDGE_PAD; view.y = -EDGE_PAD; applyView(); }
function overview() { view.scale = overviewScale(); view.x = -EDGE_PAD; view.y = -EDGE_PAD; applyView(); }
// original (normal-layout) geometry of every card, from data attributes (works while the tree is hidden)
const BOX = {}, OFF = {};
svgEl.querySelectorAll(".job-card").forEach(el => {
  const d = el.dataset;
  BOX[d.job] = {x: +d.x, y: +d.y, w: +d.w, h: +d.h, layer: +d.layer};
});
svgEl.querySelectorAll(".edge").forEach(el => { el.dataset.d = el.getAttribute("d"); });
function cardBox(job) {
  const o = BOX[job];
  if (!o) return null;
  const f = OFF[job] || [0, 0];
  return {x: o.x + f[0], y: o.y + f[1], w: o.w, h: o.h};
}
function centerOn(job) {
  const b = cardBox(job);
  if (!b) return;
  const s = viewSize(), open = document.getElementById("detail").classList.contains("open");
  const sx = (open && s.w > 900 ? s.w - 540 : s.w) / 2;
  view.x = b.x + b.w / 2 - sx / view.scale;
  view.y = b.y + b.h / 2 - s.h / 2 / view.scale;
  applyView();
}
svgEl.addEventListener("wheel", e => {
  e.preventDefault();
  const r = svgEl.getBoundingClientRect();
  if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX - r.left, e.clientY - r.top);
  else { view.x += e.deltaX / view.scale; view.y += e.deltaY / view.scale; applyView(); }
}, {passive: false});
let drag = null;
svgEl.addEventListener("mousedown", e => { drag = {x: e.clientX, y: e.clientY}; dragged = false; });
window.addEventListener("mousemove", e => {
  if (!drag || !(e.buttons & 1)) { drag = null; return; }
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (!dragged && Math.hypot(dx, dy) < 4) return;
  dragged = true; svgEl.classList.add("panning");
  view.x -= dx / view.scale; view.y -= dy / view.scale;
  drag = {x: e.clientX, y: e.clientY};
  applyView();
});
window.addEventListener("mouseup", () => { drag = null; svgEl.classList.remove("panning"); });
window.addEventListener("resize", applyView);

// ---------- path view: only the chosen path(s), re-laid out compactly ----------
const ROWGAP = 28, COLGAP = 16;
function resetLayout() {
  for (const k of Object.keys(OFF)) delete OFF[k];
  svgEl.querySelectorAll(".job-card").forEach(el => { el.removeAttribute("transform"); el.style.display = ""; });
  svgEl.querySelectorAll(".edge").forEach(el => { el.setAttribute("d", el.dataset.d); el.style.display = ""; });
  content = {w: SVG_W, h: SVG_H};
}
// Same idea as route_edges() in Python: neighbouring rows jog in the gap between them,
// edges that skip rows drop through a free lane beside the skipped cards.
function layoutPath(keep) {
  const rows = {};
  for (const j of keep) if (BOX[j]) (rows[BOX[j].layer] = rows[BOX[j].layer] || []).push(j);
  const ids = Object.keys(rows).map(Number).sort((a, b) => a - b);
  const pos = {}, rowOf = {}, rowTop = {}, rowBot = {};
  let y = 0, maxX = 0;
  ids.forEach((l, ri) => {
    const js = rows[l].sort((a, b) => BOX[a].x - BOX[b].x);
    const h = Math.max(...js.map(j => BOX[j].h));
    js.forEach((j, ci) => {
      const x = ci * (BOX[j].w + COLGAP);
      pos[j] = {x: x, y: y + (h - BOX[j].h) / 2}; rowOf[j] = ri; maxX = Math.max(maxX, x + BOX[j].w);
    });
    rowTop[ri] = y; rowBot[ri] = y + h; y += h + ROWGAP;
  });
  svgEl.querySelectorAll(".job-card").forEach(el => {
    const j = el.dataset.job;
    if (!pos[j]) { el.style.display = "none"; return; }
    const dx = pos[j].x - BOX[j].x, dy = pos[j].y - BOX[j].y;
    el.style.display = ""; el.setAttribute("transform", "translate(" + dx + " " + dy + ")"); OFF[j] = [dx, dy];
  });
  let laneMax = 0;
  svgEl.querySelectorAll(".edge").forEach(el => {
    const f = el.dataset.from, t = el.dataset.to;
    if (!(pos[f] && pos[t])) { el.style.display = "none"; return; }
    el.style.display = "";
    const x1 = pos[f].x + BOX[f].w / 2, y1 = pos[f].y + BOX[f].h, x2 = pos[t].x + BOX[t].w / 2, y2 = pos[t].y;
    const lp = rowOf[f], li = rowOf[t], ya = rowBot[lp] + ROWGAP / 2, yb = rowTop[li] - ROWGAP / 2;
    let d;
    if (li - lp <= 1) d = "M " + x1 + " " + y1 + " V " + (ya + yb) / 2 + " H " + x2 + " V " + y2;
    else {
      const mid = Object.keys(pos).filter(j => rowOf[j] > lp && rowOf[j] < li);
      const lanes = mid.map(j => pos[j].x + BOX[j].w + 8);
      const free = lanes.filter(g => !mid.some(j => pos[j].x - 6 <= g && g <= pos[j].x + BOX[j].w + 6));
      const gx = free.length ? free.reduce((a, b) => Math.abs(a - x2) <= Math.abs(b - x2) ? a : b) : (lanes.length ? Math.max(...lanes) : x2);
      laneMax = Math.max(laneMax, gx);
      d = "M " + x1 + " " + y1 + " V " + ya + " H " + gx + " V " + yb + " H " + x2 + " V " + y2;
    }
    el.setAttribute("d", d);
  });
  content = {w: Math.max(maxX, laneMax) + 20, h: y - ROWGAP + 20};
}

// A path is a job plus everything upstream of it. "@latest" follows the newest result across refreshes.
const PATH = {A: null, B: null};
const LATEST = Object.keys(JOBS).find(j => JOBS[j].latest) || null;
const jobNo = j => parseInt((j.match(/(\\d+)\\D*$/) || [0, 0])[1], 10);
const jobName = j => (JOBS[j] && JOBS[j].alias) || j;
const realJob = v => v === "@latest" ? LATEST : v;
let inPathView = false, savedView = null, panelOpen = true, viewMode = "all";  // viewMode: "all" = whole tree, "only" = just the selected paths
function ancestors(job) {
  const seen = new Set(), todo = [job];
  while (todo.length) {
    const n = todo.pop();
    if (seen.has(n) || !JOBS[n]) continue;
    seen.add(n);
    for (const p of JOBS[n].parents) todo.push(p);
  }
  return seen;
}
function savePaths() { try { sessionStorage.setItem("reliontree.paths", JSON.stringify({A: PATH.A, B: PATH.B, mode: viewMode})); } catch (e) {} }
// Selecting only highlights (and, in the full tree, scrolls to the new path's end); the view mode is a separate switch.
function selectPath(slot, v) {
  PATH[slot] = v; savePaths(); applyPaths();
  if (viewMode === "all" && v) centerOn(realJob(v));
}
function setPath(slot, job) { selectPath(slot, job); }
function clearPath(slot) { PATH[slot] = null; savePaths(); applyPaths(); }
function clearPaths() { PATH.A = PATH.B = null; savePaths(); applyPaths(); }
function showLatest() { PATH.B = null; selectPath("A", "@latest"); }
function setViewMode(m) { viewMode = m; savePaths(); applyPaths(); }
// "Path to…" menu: results worth following (refinements, post-processing, and any job nothing builds on)
function fillPathPick() {
  const hasChild = new Set(Object.keys(JOBS).flatMap(j => JOBS[j].parents));
  const jobs = Object.keys(JOBS).filter(j => document.getElementById("card-" + j) && JOBS[j].state === "succeeded" &&
    (["Refine3D", "PostProcess"].includes(jobType(j)) || !hasChild.has(j))).sort((a, b) => jobNo(b) - jobNo(a));
  const sel = document.getElementById("pathPick");
  for (const j of jobs) {
    const i = JOBS[j], o = document.createElement("option");
    o.value = j;
    o.textContent = (i.latest ? "\\u2605 " : "") + jobType(j) + " " + (i.alias || j.split("/")[1]) + (i.resolution_angstrom ? " \\u00b7 " + i.resolution_angstrom.toFixed(1) + " \\u00c5" : "");
    sel.appendChild(o);
  }
}
function pickPath(job) { if (job) selectPath(PATH.A ? "B" : "A", job); }
function markSidebar() {
  const inPath = new Set([...(PATH.A ? ancestors(realJob(PATH.A)) : []), ...(PATH.B ? ancestors(realJob(PATH.B)) : [])]);
  const any = !!(PATH.A || PATH.B);
  document.querySelectorAll(".job-item").forEach(el => el.classList.toggle("offpath", any && !inPath.has(el.dataset.job)));
}
function applyPaths(keepView) {
  const a = PATH.A && realJob(PATH.A) ? ancestors(realJob(PATH.A)) : null;
  const b = PATH.B && realJob(PATH.B) ? ancestors(realJob(PATH.B)) : null;
  const active = !!(a || b), only = active && viewMode === "only";
  if (only) {
    if (!inPathView) savedView = {x: view.x, y: view.y, scale: view.scale};
    layoutPath(new Set([...(a || []), ...(b || [])]));
    if (!keepView) { view.scale = 1; view.x = -EDGE_PAD; view.y = -EDGE_PAD; }
  } else if (inPathView) {
    resetLayout();
    if (!keepView) Object.assign(view, savedView || {x: -EDGE_PAD, y: -EDGE_PAD, scale: 1});
  }
  inPathView = only;
  svgEl.classList.toggle("pathmode", active);
  const cls = (inA, inB) => inA && inB ? "pab" : inA ? "pa" : inB ? "pb" : "";
  const mark = (el, c) => { el.classList.remove("pa", "pb", "pab"); if (c) el.classList.add(c); };
  svgEl.querySelectorAll(".job-card").forEach(el => mark(el, cls(a && a.has(el.dataset.job), b && b.has(el.dataset.job))));
  svgEl.querySelectorAll(".edge").forEach(el => mark(el, cls(
    a && a.has(el.dataset.from) && a.has(el.dataset.to), b && b.has(el.dataset.from) && b.has(el.dataset.to))));
  for (const slot of ["A", "B"]) {
    const chip = document.getElementById("p" + slot);
    chip.hidden = !PATH[slot];
    if (PATH[slot]) chip.innerHTML = slot + ": " + esc(PATH[slot] === "@latest" ? "latest \\u2192 " + jobName(LATEST) : jobName(PATH[slot])) +
      "<button title='remove' data-clear='" + slot + "'>&times;</button>";
  }
  document.getElementById("pLatest").classList.toggle("on", PATH.A === "@latest" && !PATH.B);
  document.getElementById("vAll").classList.toggle("on", !only);
  document.getElementById("vOnly").classList.toggle("on", only);
  document.getElementById("vOnly").disabled = !active;
  document.getElementById("pClear").hidden = !active;
  renderPathPanel(a, b);
  markSidebar();
  applyView();
}
document.getElementById("pathBar").addEventListener("click", e => {
  const slot = e.target.dataset && e.target.dataset.clear;
  if (slot) clearPath(slot);
});
document.getElementById("pathPanel").addEventListener("click", e => {
  if (e.target.closest(".ptoggle")) { panelOpen = !panelOpen; applyPaths(true); }
});
function jobCell(j) {
  const i = JOBS[j], bits = [];
  if (i.resolution_angstrom) bits.push(i.resolution_angstrom.toFixed(1) + " \\u00c5");
  if (i.n_particles) bits.push(i.n_particles.toLocaleString("en-US"));
  return "<b>" + esc(jobType(j)) + "</b> " + esc(i.alias || j.split("/")[1]) + (i.alias ? " <span class=sub>" + esc(j.split("/")[1]) + "</span>" : "") +
    (bits.length ? "<br><span class=sub>" + bits.join(" \\u00b7 ") + "</span>" : "");
}
function endCell(j) {
  const i = JOBS[j];
  return "<b>" + esc(jobName(j)) + "</b><br><span class=sub>" + (i.resolution_angstrom ? i.resolution_angstrom.toFixed(1) + " \\u00c5" : "no resolution") +
    (i.n_particles ? " \\u00b7 " + i.n_particles.toLocaleString("en-US") + " particles" : "") + "</span>";
}
function renderPathPanel(a, b) {
  const panel = document.getElementById("pathPanel");
  if (!a && !b) { panel.hidden = true; return; }
  panel.hidden = false;
  const head = t => "<span class=ptoggle>" + (panelOpen ? "\\u25be " : "\\u25b8 ") + t + "</span>";
  const byNo = (x, y) => jobNo(x) - jobNo(y);
  if (!(a && b)) {
    const set = a || b, end = realJob(a ? PATH.A : PATH.B);
    panel.innerHTML = head("<b>Path to " + esc(jobName(end)) + "</b> &middot; " + set.size + " jobs") +
      " <span class=sub>&mdash; select any job and press <b>Path B</b> in its panel to compare a second path. Use <b>Full tree</b> / <b>Selection only</b> to switch the view.</span>";
    return;
  }
  const endA = realJob(PATH.A), endB = realJob(PATH.B);
  const onlyA = Array.from(a).filter(j => !b.has(j)).sort(byNo), onlyB = Array.from(b).filter(j => !a.has(j)).sort(byNo);
  const shared = Array.from(a).filter(j => b.has(j)).sort(byNo);
  const fork = shared.length ? shared[shared.length - 1] : null;
  let rows = "";
  for (let k = 0; k < Math.max(onlyA.length, onlyB.length); k++)
    rows += "<tr><td class=a>" + (onlyA[k] ? jobCell(onlyA[k]) : "") + "</td><td class=b>" + (onlyB[k] ? jobCell(onlyB[k]) : "") + "</td></tr>";
  let chg = "";
  for (const ja of onlyA) {
    const jb = onlyB.find(x => jobType(x) === jobType(ja));
    if (!jb) continue;
    const ch = diffOptions(JOBS[ja].options, JOBS[jb].options).changed, keys = Object.keys(ch);
    chg = "<p><b>First comparable step: " + esc(jobType(ja)) + "</b> &mdash; " + keys.length + " parameter(s) differ" +
      (keys.length ? ":<br><span class=chg>" + keys.slice(0, 12).map(k => esc(k) + ": " + esc(ch[k][0]) + " &rarr; " + esc(ch[k][1])).join("<br>") +
        (keys.length > 12 ? "<br>&hellip;" : "") + "</span>" : "") + "</p>";
    break;
  }
  panel.innerHTML = head("<b>Path A vs. B</b> &middot; " + shared.length + " shared jobs" +
    (fork ? ", paths diverge after <b>" + esc(jobName(fork)) + "</b>" : ", no common ancestor")) +
    (!panelOpen ? "" : "<table><tr><th class=a>A &middot; " + onlyA.length + " own jobs</th><th class=b>B &middot; " + onlyB.length + " own jobs</th></tr>" +
    "<tr><td class=a>" + endCell(endA) + "</td><td class=b>" + endCell(endB) + "</td></tr>" + rows + "</table>" + chg);
}
fillPathPick();
function restorePaths() {
  let saved = null, vp = null;
  try { saved = JSON.parse(sessionStorage.getItem("reliontree.paths") || "null"); vp = JSON.parse(sessionStorage.getItem("reliontree.vp") || "null"); } catch (e) {}
  if (saved && saved.mode) viewMode = saved.mode;
  if (saved) for (const k of ["A", "B"]) PATH[k] = saved[k] && (saved[k] === "@latest" || JOBS[saved[k]]) ? saved[k] : null;
  if (vp && isFinite(vp.scale)) Object.assign(view, vp);
  applyPaths(!!vp);
}
"""
