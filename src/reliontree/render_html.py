"""Wrap the dependency-free SVG job-tree render in a minimal self-contained
HTML page. No JS framework, no server required — opens directly via
`file://` in any browser. Pure stdlib."""

import html
import json

from .view_assets import VIEW_CSS, VIEW_JS
from .relion_treebuild import pick_classes, render_svg, ordered_jobs, job_type, JOB_TYPE_COLORS, DEFAULT_TYPE_COLOR
from .relion_classes import class_advice, class_iter_thumbs, SETTLED_CHANGES, TINY_SHARE
from .relion_export import history_rows, rows_to_csv
from .theme import THEME_CSS

_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>reliontree — {title_short}</title>
<style>
{theme_css}
  body {{ display: flex; height: 100vh; margin: 0; }}
  h1 {{ font-size: 14px; color: var(--text-muted); margin: 0 0 12px 0; word-break: break-all; }}
  #sidebar {{ width: 280px; flex: none; overflow-y: auto; border-right: 1px solid var(--border);
              background: var(--surface); padding: 12px 0; }}
  #sidebar input[type=text] {{ width: calc(100% - 24px); margin: 0 12px 8px; padding: 6px; box-sizing: border-box; }}
  .job-item {{ display: flex; flex-wrap: wrap; align-items: center; gap: 2px 6px;
               padding: 5px 12px 5px 9px; cursor: pointer; font-size: 12px; border-left: 4px solid transparent; }}
  .job-item.side .job-label {{ opacity: 0.6; }}
  .job-item .jid {{ font-size: 10px; color: var(--text-muted); }}
  .job-item .star {{ color: var(--accent); font-size: 11px; }}
  .job-item:hover {{ background: var(--neutral-bg) !important; }}
  .job-item.selected {{ background: var(--accent-bg) !important; font-weight: bold; }}
  .job-item .job-label {{ flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .job-item .job-meta {{ flex: 0 0 100%; display: flex; align-items: center; gap: 6px;
                          font-size: 11px; color: var(--text-muted); padding-left: 20px; }}
  .job-item .tree-btn {{ flex: none; font-size: 11px; padding: 1px 6px; border: 1px solid var(--border);
                          border-radius: 4px; background: var(--surface); cursor: pointer; color: var(--text); }}
  .job-item .tree-btn:hover {{ background: var(--accent-bg); }}
  .job-item input[type=checkbox] {{ flex: none; margin: 0; }}
  .job-item .badge {{ flex: none; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  .badge-running {{ animation: pulse 1.5s ease-in-out infinite; }}
  #compareBar {{ padding: 6px 12px; font-size: 11px; color: var(--text-muted); display: flex;
                 flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 4px;
                 border-bottom: 1px solid var(--border); }}
  #compareBar button {{ font-size: 11px; padding: 3px 8px; }}
  #compareBar button:disabled {{ color: var(--text-muted); cursor: default; opacity: 0.5; }}
  .drawer table.diff td, .modal-box table.diff td {{ border-bottom: 1px solid var(--border); }}
  .drawer table.diff td:not(.key) {{ word-break: break-word; }}
  .drawer table.diff td.diff-key {{ white-space: normal; word-break: break-word; }}
  .drawer .diff-key, .modal-box .diff-key {{ font-weight: bold; }}
  .modal-box table.diff th {{ text-align: left; padding: 4px 10px 4px 0; border-bottom: 1px solid var(--border); }}
  .drawer .why-btn {{ font-size: 12px; margin-bottom: 12px; }}
  #main {{ flex: 1; overflow: auto; padding: 24px; }}
  .wrap {{ overflow: auto; padding: 12px; }}
  .job-card {{ cursor: pointer; }}
  .job-card, .edge {{ transition: opacity 0.12s; }}
  svg .dim {{ opacity: 0.15 !important; }}
  .focus-main .job-card:not(.main), .focus-main .edge:not(.main) {{ opacity: 0.18 !important; }}
  #updated {{ font-size: 12px; color: var(--text-muted); align-self: center; margin-left: 8px; }}
  #toolbar button.on {{ background: var(--accent-bg); border-color: var(--accent); }}
  #toolbar {{ margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }}
  #toolbar button {{ font-size: 12px; }}
  #toolbar label {{ font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 4px; margin-left: 8px; }}
  #jobTable tbody tr {{ cursor: pointer; }}
  #jobTable tbody tr:hover {{ background: var(--neutral-bg); }}

  /* Both side panels are the same kind of thing: a slide-in drawer fixed to
     the right edge, opened by a toolbar button, one at a time. Neither
     reserves permanent layout width the way the old always-on #browse
     sidebar did. */
  .drawer {{ position: fixed; top: 0; right: 0; height: 100vh; width: 320px;
             background: var(--surface); border-left: 1px solid var(--border); box-shadow: var(--shadow);
             padding: 16px; font-size: 13px; overflow-y: auto; overflow-x: hidden;
             transform: translateX(100%); transition: transform 0.15s ease; z-index: 20; }}
  .drawer.open {{ transform: translateX(0); }}
  #detail {{ width: min(540px, 100vw); }}
  .drawer .chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 12px 0; }}
  .drawer .chip {{ background: var(--neutral-bg); border-radius: 12px; padding: 2px 10px; font-size: 12px; }}
  .drawer details.sec {{ border-top: 1px solid var(--border); padding: 8px 0; }}
  .drawer details.sec > summary {{ font-weight: bold; font-size: 14px; cursor: pointer; padding: 4px 0; }}
  .drawer h2, .drawer h3, .modal-box h2, .modal-box h3 {{ margin: 0 0 12px 0; font-size: 15px; }}
  .drawer .close-btn, .modal-box .close-btn {{ float: right; border: none; background: none; font-size: 16px;
                         cursor: pointer; color: var(--text-muted); line-height: 1; }}
  .drawer .close-btn:hover, .modal-box .close-btn:hover {{ color: var(--text); }}
  .drawer table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
  .modal-box table {{ border-collapse: collapse; width: 100%; }}
  .drawer td, .modal-box td {{ padding: 3px 8px 3px 0; vertical-align: top; font-size: 12px; border-bottom: none; }}
  .drawer td.key {{ color: var(--text-muted); white-space: nowrap; }}
  .drawer .path {{ word-break: break-all; color: var(--text); margin-bottom: 10px; font-size: 12px; }}
  .drawer .note, .modal-box .note {{ color: var(--text-muted); font-style: italic; font-size: 12px; }}
  .drawer button.nav {{ display: block; width: 100%; text-align: left; margin-bottom: 4px;
                         padding: 6px 8px; font-size: 12px; color: var(--accent); }}
  .drawer button.nav:hover {{ background: var(--accent-bg); }}
  .drawer button.nav.open-project {{ color: var(--accent-text); background: var(--accent); border-color: var(--accent); font-weight: bold; }}
  .drawer button.nav.open-project:hover {{ filter: brightness(0.9); }}

  /* Compare needs real width for N side-by-side values -- the 320px
     side drawer that works for a single job's key/value list was always
     too cramped for this, hence the separate centered modal. */
  .modal-overlay {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.4);
                     z-index: 30; align-items: center; justify-content: center; }}
  .modal-overlay.open {{ display: flex; }}
  .modal-box {{ position: relative; background: var(--surface); border-radius: var(--radius);
                box-shadow: var(--shadow); padding: 24px; width: min(900px, 92vw);
                max-height: 85vh; overflow-y: auto; overflow-x: auto; }}
  .modal-box table.diff {{ table-layout: auto; }}
  .modal-box td.diff-key {{ padding-top: 10px; }}
{view_css}
</style>
</head>
<body>
<div id="sidebar">
  <input id="jobFilter" type="text" placeholder="filter jobs...">
  <div id="filterRow" style="display:flex; gap:6px; margin:0 12px 8px;">
    <select id="typeFilter" style="flex:1; min-width:0;"><option value="">all types</option></select>
    <select id="stateFilter" style="flex:1; min-width:0;">
      <option value="">all states</option>
      <option value="succeeded">succeeded</option>
      <option value="failed">failed</option>
      <option value="running">running</option>
      <option value="aborted">aborted</option>
      <option value="scheduled">scheduled</option>
      <option value="missing">missing</option>
      <option value="unknown">unknown</option>
    </select>
  </div>
  <div style="margin:0 12px 8px;">
    <select id="convFilter" style="width:100%;" title="Class2D/Class3D only: share of particles still switching class in the last iteration">
      <option value="">any convergence</option>
      <option value="open">not converged (&gt;5% switching)</option>
      <option value="done">converged (&le;5% switching)</option>
    </select>
  </div>
  <div id="compareBar">
    <span id="compareCount">0 selected</span>
    <button id="compareBtn" disabled onclick="showCompare()">Compare</button>
  </div>
  <div id="jobList"></div>
</div>
<div id="main">
<h1 title="{title}">{title_short}{experiment_badge}</h1>
<div id="toolbar">
  <button id="viewToggle" onclick="toggleView()">&#9638; Table view</button>
  <select id="exportSel" onchange="doExport(this.value); this.value = ''" title="export the tree or the table">
    <option value="">Export&hellip;</option><option value="svg">SVG (tree)</option><option value="png">PNG (tree)</option>
    <option value="csv">CSV (table)</option><option value="json">JSON (data)</option></select>
  <button onclick="location.reload()">&#8635; Update now</button>
  <span id="pathBar"><span class="lbl">Paths</span>
    <span class="seg"><button id="vAll" class="on" onclick="setViewMode('all')" title="whole tree, selected paths highlighted">Full tree</button><button id="vOnly" onclick="setViewMode('only')" disabled title="only the selected paths, laid out compactly">Selection only</button></span>
    <button id="pLatest" onclick="showLatest()" title="path that led to the latest result">&#9733; Latest</button>
    <select id="pathPick" onchange="pickPath(this.value); this.value = ''" title="choose a result to show its path (first pick = A, next = B)"><option value="">Path to&hellip;</option></select>
    <span id="pA" class="pchip pchip-a" hidden></span><span id="pB" class="pchip pchip-b" hidden></span>
    <button id="pClear" onclick="clearPaths()" title="deselect both paths" hidden>Clear</button></span>
  <span id="zoomBar"><button onclick="zoomBy(1/1.25)" title="zoom out">&minus;</button><button onclick="zoomBy(1.25)" title="zoom in">+</button>
    <button onclick="actualSize()" title="cards at actual size, back to the top">100%</button><button onclick="overview()" title="whole tree on one screen">Overview</button></span>
  {auto_refresh_toggle}
  <span id="updated"></span>
  <button onclick="openDrawer('browse')" style="margin-left:auto">&#128194; Browse project</button>
</div>
{scope_banner}
<div id="pathPanel" hidden></div>
<div class="wrap" id="treeView">
{svg}
</div>
<div class="wrap" id="tableView" style="display:none">
  <table id="jobTable"><thead><tr>
    <th>Job</th><th>Type</th><th>State</th><th>Parent(s)</th><th>Resolution</th><th>Particles</th><th>Switch/it</th>
  </tr></thead><tbody></tbody></table>
</div>
</div>
<div id="detail" class="drawer"></div>
<div id="compareModal" class="modal-overlay" onclick="if (event.target === this) closeCompareModal()">
  <div class="modal-box">
    <button class="close-btn" onclick="closeCompareModal()">&times;</button>
    <div id="compareModalBody"></div>
  </div>
</div>
{browse_panel}
<script>
const JOBS = {jobs_json};
const CSV_TEXT = {csv_json};
const INTERACTIVE = {interactive_json};
const TYPE_COLORS = {type_colors_json};

function download(filename, text, mime) {{
  const blob = new Blob([text], {{type: mime}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}}

function svgSource() {{
  // export the whole tree at 1:1, not the current pan/zoom window
  const c = document.querySelector(".wrap svg").cloneNode(true);
  c.setAttribute("width", c.dataset.w); c.setAttribute("height", c.dataset.h);
  c.setAttribute("viewBox", "0 0 " + c.dataset.w + " " + c.dataset.h);
  return new XMLSerializer().serializeToString(c);
}}

function exportSvg() {{
  download("tree.svg", svgSource(), "image/svg+xml");
}}

function exportPng() {{
  const svg = document.querySelector(".wrap svg");
  const w = +svg.dataset.w, h = +svg.dataset.h;
  const img = new Image();
  const svgBlob = new Blob([svgSource()], {{type: "image/svg+xml;charset=utf-8"}});
  const url = URL.createObjectURL(svgBlob);
  img.onload = () => {{
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(img, 0, 0, w, h);
    URL.revokeObjectURL(url);
    canvas.toBlob(blob => {{
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "tree.png";
      a.click();
      URL.revokeObjectURL(a.href);
    }});
  }};
  img.src = url;
}}

function doExport(kind) {{
  ({{svg: exportSvg, png: exportPng, csv: exportCsv, json: exportJson}})[kind]?.();
}}

function exportCsv() {{
  download("jobs.csv", CSV_TEXT, "text/csv");
}}

function exportJson() {{
  download("jobs.json", JSON.stringify(JOBS, null, 2), "application/json");
}}

function esc(s) {{
  if (s === undefined || s === null) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}}

// Lineage highlight: hovering (or selecting) a job keeps its ancestors and
// descendants lit and dims the rest of the tree. Pure DOM, uses JOBS[*].parents.
let pinned = null;
function lineage(job) {{
  const kids = {{}};
  for (const j of Object.keys(JOBS)) for (const p of JOBS[j].parents) (kids[p] = kids[p] || []).push(j);
  const keep = new Set([job]);
  for (const [next, start] of [[j => JOBS[j] ? JOBS[j].parents : [], job], [j => kids[j] || [], job]]) {{
    const todo = [start];
    while (todo.length) for (const n of next(todo.pop())) if (!keep.has(n)) {{ keep.add(n); todo.push(n); }}
  }}
  return keep;
}}
function highlight(job) {{
  if (typeof PATH !== "undefined" && (PATH.A || PATH.B)) job = null;
  const keep = job ? lineage(job) : null;
  document.querySelectorAll("svg .job-card").forEach(el => el.classList.toggle("dim", !!keep && !keep.has(el.dataset.job)));
  document.querySelectorAll("svg .edge").forEach(el => el.classList.toggle("dim", !!keep && !(keep.has(el.dataset.from) && keep.has(el.dataset.to))));
}}

function openDrawer(id) {{
  document.querySelectorAll(".drawer").forEach(el => el.classList.toggle("open", el.id === id));
}}

function closeDrawers() {{
  pinned = null;
  highlight(null);
  try {{ history.replaceState(null, "", location.pathname + location.search); }} catch (e) {{}}
  document.querySelectorAll(".drawer").forEach(el => el.classList.remove("open"));
}}

const compareSelection = new Set();

function jobType(job) {{
  return job.split("/")[0];
}}

function formatDuration(seconds) {{
  if (!seconds && seconds !== 0) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return (h ? h + "h " : "") + m + "m";
}}

// Same rules as relion_diff.diff_options/diff_many_options in Python (kept
// in sync by hand -- small enough that a shared build step isn't worth it).
function diffOptions(a, b) {{
  const keys = Array.from(new Set([...Object.keys(a), ...Object.keys(b)])).sort();
  const changed = {{}}, unchanged = {{}};
  for (const k of keys) {{
    const va = a[k], vb = b[k];
    if (va !== vb) changed[k] = [va, vb]; else unchanged[k] = va;
  }}
  return {{changed, unchanged}};
}}

function diffManyOptions(jobsOptions) {{
  const jobs = Object.keys(jobsOptions);
  const keys = Array.from(new Set(jobs.flatMap(j => Object.keys(jobsOptions[j])))).sort();
  const varying = {{}}, constant = {{}};
  for (const k of keys) {{
    const values = {{}};
    for (const j of jobs) values[j] = jobsOptions[j][k];
    const distinct = new Set(Object.values(values));
    if (distinct.size > 1) varying[k] = values; else constant[k] = values[jobs[0]];
  }}
  return {{varying, constant}};
}}

function updateCompareBar() {{
  document.getElementById("compareCount").textContent = compareSelection.size + " selected";
  document.getElementById("compareBtn").disabled = compareSelection.size < 2;
}}

function showCompare() {{
  // A real side-by-side table (one column per job) in the wide modal --
  // the narrow 320px side drawer never had room for N value columns,
  // which is what forced scrolling either direction.
  const jobs = Array.from(compareSelection);
  const jobsOptions = {{}};
  for (const j of jobs) jobsOptions[j] = JOBS[j].options;
  const {{varying}} = diffManyOptions(jobsOptions);
  let rows = "";
  for (const k of Object.keys(varying).sort()) {{
    rows += "<tr><td class='key diff-key'>" + esc(k) + "</td>" +
      jobs.map(j => "<td>" + esc(varying[k][j]) + "</td>").join("") + "</tr>";
  }}
  const header = "<tr><th>Parameter</th>" + jobs.map(j => "<th>" + esc(j) + "</th>").join("") + "</tr>";
  let body = "<h2>Compare " + jobs.length + " jobs</h2>" +
    "<table class=diff><thead>" + header + "</thead><tbody>" +
    (rows || "<tr><td class=note colspan=" + (jobs.length + 1) + ">(all identical)</td></tr>") +
    "</tbody></table>";
  const clsJobs = jobs.filter(j => (JOBS[j].classes || []).length).sort();
  if (clsJobs.length > 1) {{
    body += "<h3 style='margin-top:20px'>Particle overlap between classifications</h3>";
    if (!INTERACTIVE) body += "<p class=note>Overlap is computed live &mdash; run <code>reliontree watch</code> to see it here, or <code>reliontree overlap</code> on the command line.</p>";
    for (let i = 0; i + 1 < clsJobs.length && INTERACTIVE; i++) body += "<div class=overlap data-a='" + esc(clsJobs[i]) + "' data-b='" + esc(clsJobs[i + 1]) + "'><p class=note>loading " + esc(clsJobs[i]) + " &rarr; " + esc(clsJobs[i + 1]) + "&hellip;</p></div>";
  }}
  document.getElementById("compareModalBody").innerHTML = body;
  document.getElementById("compareModal").classList.add("open");
  document.querySelectorAll("#compareModalBody .overlap").forEach(el => loadOverlap(el));
}}

// Heatmap: row = class of job A, column = class of job B, cell shade and %
// = share of that A class's particles that ended up in that B class.
function loadOverlap(el) {{
  const a = el.dataset.a, b = el.dataset.b;
  fetch("/overlap?a=" + encodeURIComponent(a) + "&b=" + encodeURIComponent(b)).then(r => r.json()).then(j => {{
    if (j.error) {{ el.innerHTML = "<p class=note>" + esc(a) + " &rarr; " + esc(b) + ": " + esc(j.error) + "</p>"; return; }}
    const cnt = (x, y) => j.counts[x + "," + y] || 0;
    let t = "<p style='margin:12px 0 4px'><b>" + esc(a) + "</b> (rows) &rarr; <b>" + esc(b) + "</b> (columns, best match first), % of each row's particles &mdash; <b>" +
      Math.round(j.score * 100) + "%</b> of particles on the diagonal</p><table class=diff style='width:auto'><tr><td></td>" +
      j.order_b.map(y => "<th>c" + y + "</th>").join("") + "</tr>";
    for (const x of j.classes_a) {{
      const tot = j.classes_b.reduce((sum, y) => sum + cnt(x, y), 0) || 1;
      t += "<tr><th>c" + x + "</th>" + j.order_b.map(y => {{
        const f = cnt(x, y) / tot;
        return "<td title='" + cnt(x, y).toLocaleString('en-US') + " particles' style='text-align:center;min-width:48px;padding:6px;background:color-mix(in srgb, var(--accent) " +
          Math.round(f * 100) + "%, transparent)'>" + (f * 100).toFixed(0) + "%</td>";
      }}).join("") + "</tr>";
    }}
    el.innerHTML = t + "</table>";
  }}).catch(() => {{ el.innerHTML = "<p class=note>overlap request failed</p>"; }});
}}

function closeCompareModal() {{
  document.getElementById("compareModal").classList.remove("open");
}}

function showWhy(job) {{
  const info = JOBS[job];
  const siblings = Object.keys(JOBS).filter(other =>
    other !== job && JOBS[other].parents.some(p => info.parents.includes(p)));
  const sameTypeParent = info.parents.find(p => jobType(p) === jobType(job));

  let body = "<h2>" + esc(job) + " vs. its parent job</h2>";
  body += "<p class=note>Where this job comes from, and (if its parent is the same job type) exactly which parameters you changed to get here.</p>";
  body += "<p class=note>Parent(s): " + (info.parents.map(esc).join(", ") || "(none)") + "</p>";
  body += "<p class=note>Sibling(s) &mdash; other jobs from the same parent: " + (siblings.map(esc).join(", ") || "(none)") + "</p>";
  if (sameTypeParent) {{
    const {{changed}} = diffOptions(JOBS[sameTypeParent].options, info.options);
    body += "<h3>Parameters changed from " + esc(sameTypeParent) + "</h3><table class=diff>";
    for (const k of Object.keys(changed).sort()) {{
      body += "<tr><td class='key diff-key'>" + esc(k) + "</td><td>" + esc(changed[k][0]) +
        " &rarr; " + esc(changed[k][1]) + "</td></tr>";
    }}
    body += (Object.keys(changed).length ? "" : "<tr><td class=note>(none -- identical options)</td></tr>") + "</table>";
  }} else if (info.parents.length) {{
    body += "<p class=note>(parent is a different job type -- options aren't comparable)</p>";
  }}
  const detail = document.getElementById("detail");
  detail.innerHTML = "<button class='close-btn' onclick='closeDrawers()'>&times;</button>" + body;
  openDrawer("detail");
}}

function toggleView() {{
  const showingTable = document.getElementById("tableView").style.display !== "none";
  document.getElementById("treeView").style.display = showingTable ? "" : "none";
  document.getElementById("tableView").style.display = showingTable ? "none" : "";
  document.getElementById("viewToggle").textContent = showingTable ? "Table view" : "Tree view";
  if (!showingTable) renderTableView(); else if (typeof applyView === "function") applyView();
  // Auto-refresh does a real location.reload() (see below), which always
  // comes back on tree view -- same "my choice keeps resetting" bug as
  // the sidebar filters, fixed the same way: persist across the reload.
  try {{ sessionStorage.setItem("reliontree.view", showingTable ? "tree" : "table"); }} catch (e) {{}}
}}

const SETTLED = {settled}, TINY = {tiny};
// Share of particles that switched class in the last iteration (it0 is the
// untrained start and meaningless); null for non-classification jobs.
function switchRate(job) {{
  const h = (JOBS[job].classes || []).filter(x => x.changes_classes !== null && x.iter > 0);
  return h.length > 1 ? h[h.length - 1].changes_classes : null;
}}
function switchHtml(job) {{
  const r = switchRate(job);
  if (r === null) return "";
  return "<span style='color:" + (r <= SETTLED ? "#2e7d32" : "#e65100") + "'>" + (r * 100).toFixed(1) + "%</span>";
}}

function renderTableView() {{
  const body = document.querySelector("#jobTable tbody");
  body.innerHTML = "";
  for (const job of Object.keys(JOBS)) {{
    const info = JOBS[job];
    const tr = document.createElement("tr");
    tr.onclick = () => {{ toggleView(); selectJob(job); }};
    tr.innerHTML = "<td>" + esc(job) + (info.alias ? " <span class=note>" + esc(info.alias) + "</span>" : "") + "</td><td>" + esc(jobType(job)) + "</td>" +
      "<td><span class='badge badge-" +
      ({{succeeded: "good", failed: "bad", running: "warn", aborted: "warn"}}[info.state] || "neutral") +
      "'>" + esc(info.state) + "</span></td>" +
      "<td>" + esc(info.parents.join(", ")) + "</td>" +
      "<td>" + (info.resolution_angstrom ? info.resolution_angstrom.toFixed(1) + " Å" : "") + "</td>" +
      "<td>" + (info.n_particles ? info.n_particles.toLocaleString('en-US') : "") + "</td>" +
      "<td>" + switchHtml(job) + "</td>";
    body.appendChild(tr);
  }}
}}

// Jobs whose folder is gone (trimmed or deposited projects) are hidden in the list until asked for.
let showMissing = false;
try {{ showMissing = sessionStorage.getItem("reliontree.showMissing") === "1"; }} catch (e) {{}}
function toggleMissing() {{
  showMissing = !showMissing;
  try {{ sessionStorage.setItem("reliontree.showMissing", showMissing ? "1" : "0"); }} catch (e) {{}}
  renderJobList(document.getElementById("jobFilter").value);
}}

function renderJobList(filter) {{
  const list = document.getElementById("jobList");
  const typeFilter = document.getElementById("typeFilter").value;
  const stateFilter = document.getElementById("stateFilter").value;
  const convFilter = document.getElementById("convFilter").value;
  list.innerHTML = "";
  const nMissing = Object.keys(JOBS).filter(j => JOBS[j].state === "missing").length;
  const missingVisible = showMissing || stateFilter === "missing";
  if (nMissing && stateFilter !== "missing") {{
    const row = document.createElement("div");
    row.className = "missing-toggle";
    row.textContent = (showMissing ? "\u25be hide " : "\u25b8 show ") + nMissing + " missing jobs (folder not on disk)";
    row.onclick = toggleMissing;
    list.appendChild(row);
  }}
  for (const job of Object.keys(JOBS)) {{
    if (JOBS[job].state === "missing" && !missingVisible) continue;
    if (filter && (job + " " + JOBS[job].alias + " " + JOBS[job].notes + " " + JOBS[job].state + " " + JOBS[job].annotations.map(a => a.label).join(" ")).toLowerCase().indexOf(filter.toLowerCase()) === -1) continue;
    if (typeFilter && jobType(job) !== typeFilter) continue;
    if (stateFilter && JOBS[job].state !== stateFilter) continue;
    if (convFilter) {{
      const r = switchRate(job);
      if (r === null || (convFilter === "open") !== (r > SETTLED)) continue;
    }}
    const div = document.createElement("div");
    div.className = "job-item";
    div.dataset.job = job;
    const jobColor = TYPE_COLORS[job] || "#616161";
    div.style.borderLeftColor = jobColor;
    if (JOBS[job].side) div.classList.add("side");

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.title = "Select for Compare";
    checkbox.checked = compareSelection.has(job);
    checkbox.onclick = (e) => {{
      e.stopPropagation();
      if (checkbox.checked) compareSelection.add(job); else compareSelection.delete(job);
      updateCompareBar();
    }};
    div.appendChild(checkbox);

    const info = JOBS[job];
    const label = document.createElement("span");
    label.className = "job-label";
    label.textContent = JOBS[job].alias || job;
    label.title = job + (JOBS[job].notes ? "\\n" + JOBS[job].notes : "");
    div.appendChild(label);
    if (JOBS[job].annotations.length) {{
      const worst = JOBS[job].annotations[0], flag = document.createElement("span");
      flag.className = "flag lvl-" + worst.level;
      flag.textContent = "\u2691";
      flag.title = JOBS[job].annotations.map(a => a.source + ": " + a.label).join("\\n");
      div.appendChild(flag);
    }}
    if (JOBS[job].alias) {{
      const jid = document.createElement("span");
      jid.className = "jid";
      jid.textContent = job.split("/")[1];
      div.appendChild(jid);
    }}
    if (JOBS[job].latest || JOBS[job].best) {{
      const star = document.createElement("span");
      star.className = "star";
      star.textContent = "\u2605";
      star.title = [JOBS[job].latest ? "latest result" : "", JOBS[job].best ? "best resolution" : ""].filter(Boolean).join(" + ");
      div.appendChild(star);
    }}
    div.onclick = () => selectJob(job);
    if (document.getElementById("card-" + job)) {{
      for (const slot of ["A", "B"]) {{
        const pb = document.createElement("button");
        pb.type = "button"; pb.className = "pick pick-" + slot.toLowerCase(); pb.textContent = slot;
        pb.title = "show the path to this job as path " + slot + (slot === "B" ? " (compare)" : "");
        pb.onclick = (e) => {{ e.stopPropagation(); setPath(slot, job); }};
        div.appendChild(pb);
      }}
    }}
    if (INTERACTIVE) {{
      const btn = document.createElement("button");
      btn.className = "tree-btn";
      btn.type = "button";
      btn.title = "Build tree from this job";
      btn.textContent = "tree";
      btn.onclick = (e) => {{
        e.stopPropagation();
        location.href = "/?job=" + encodeURIComponent(job);
      }};
      div.appendChild(btn);
    }}

    const meta = document.createElement("span");
    meta.className = "job-meta";
    const stateBadge = document.createElement("span");
    const stateLevel = {{succeeded: "good", failed: "bad", running: "warn", aborted: "warn"}}[info.state] || "neutral";
    stateBadge.className = "badge badge-" + stateLevel + (info.state === "running" ? " badge-running" : "");
    stateBadge.textContent = info.state;
    meta.appendChild(stateBadge);
    let extra = "";
    if (info.resolution_angstrom) extra += info.resolution_angstrom.toFixed(1) + " Å";
    if (info.n_particles) extra += (extra.trim() ? "  " : "") + info.n_particles.toLocaleString('en-US');
    if (extra) meta.appendChild(document.createTextNode(extra));
    const sw = document.createElement("span");
    sw.innerHTML = switchHtml(job) ? "&#8635; " + switchHtml(job) : "";
    sw.title = "particles switching class in the last iteration";
    meta.appendChild(sw);
    div.appendChild(meta);

    list.appendChild(div);
  }}
  try {{ markSidebar(); }} catch (e) {{}}  // path view not initialised yet on the first call
}}

// Collapsed by default. One card per class (map thumbnail, share bar) and
// a convergence chart: % of particles that switched class each iteration,
// dashed line = the 5% "settled" level the copilot uses.
const CLASS_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#9c755f"];
const classThumbCache = {{}};
function chosenBy(job, i) {{ const c = job && JOBS[job].chosen[i + 1]; return c ? c.join(", ") : ""; }}
function classCards(hist, idx, thumbs, flags, job) {{
  const e = hist[idx];
  return e.shares.map((s, i) => {{
    const kept = flags ? flags[i] : null;
    const tiny = kept === false || (kept === null && s < TINY);
    return "<div style='display:flex;align-items:center;gap:8px;margin:4px 0" + (tiny ? ";opacity:.45" : "") +
      (kept ? ";border-left:4px solid #2e7d32;padding-left:6px" : "") + "'>" +
      (thumbs && thumbs[i] ? "<img src='" + thumbs[i] + "' width=80 height=80 style='border-radius:4px;cursor:zoom-in' title='enlarge' onclick='bigClass(" + i + ")'>" : "") +
      "<div style='flex:1'><div style='font-size:12px'>class " + (i + 1) + " &middot; " + (s * 100).toFixed(1) + "%" +
      (chosenBy(job, i) ? " &middot; <b style='color:#2e7d32'>&#10003; kept by " + esc(chosenBy(job, i)) + "</b>" : "") +
      (kept === true ? " &middot; <b style='color:#2e7d32'>&#10003; selected</b>" : kept === false ? " &middot; discarded" :
        tiny ? " &middot; nearly empty" : "") + "</div>" +
      "<div style='background:var(--border);height:8px;border-radius:4px'><div style='height:8px;border-radius:4px;background:" +
      CLASS_COLORS[i % CLASS_COLORS.length] + ";width:" + Math.max(1, Math.round(s * 100)) + "%'></div></div></div></div>";
  }}).join("");
}}

// Slider over iterations (watch mode: thumbnails are fetched per iteration
// on demand; a static export only has the final iteration's thumbnails).
let classCtx = null;
function setClassIter(idx) {{
  const c = classCtx, e = c.hist[idx];
  c.idx = idx;
  document.getElementById("classIterLabel").textContent = "iteration " + e.iter;
  const paint = th => {{ if (c.idx === idx) document.getElementById("classCards").innerHTML = classCards(c.hist, idx, th, null, c.job); }};
  if (!INTERACTIVE) {{ paint(idx === c.hist.length - 1 ? c.thumbs : null); return; }}
  const key = c.job + "@" + e.iter;
  if (classThumbCache[key]) {{ paint(classThumbCache[key]); return; }}
  paint(null);
  fetch("/class-thumbs?job=" + encodeURIComponent(c.job) + "&it=" + e.iter + "&size=80")
    .then(r => r.json()).then(j => {{ classThumbCache[key] = j.thumbs || []; paint(classThumbCache[key]); }}).catch(() => {{}});
}}

function bigClass(i) {{
  const c = classCtx, e = c.hist[c.idx];
  const key = c.job + "@" + e.iter;
  const show = uri => {{
    document.getElementById("compareModalBody").innerHTML = "<h2>" + esc(c.job) + " &middot; class " + (i + 1) + " &middot; iteration " +
      e.iter + "</h2><img src='" + uri + "' style='width:min(100%,520px);image-rendering:auto;border-radius:6px'>";
    document.getElementById("compareModal").classList.add("open");
  }};
  if (!INTERACTIVE) {{ const t = c.thumbs && c.thumbs[i]; if (t) show(t); return; }}
  fetch("/class-thumbs?job=" + encodeURIComponent(c.job) + "&it=" + e.iter + "&size=360")
    .then(r => r.json()).then(j => {{ if (j.thumbs && j.thumbs[i]) show(j.thumbs[i]); }}).catch(() => {{}});
}}

// "Select classes" job: the parent classification's classes at its final
// iteration, kept ones marked (RELION only stores positional keep flags).
function selectionBlock(info) {{
  const sel = info.selection;
  if (!sel) return "";
  const hist = JOBS[sel.parent].classes, idx = hist.length - 1;
  const kept = sel.flags.map((f, i) => f ? i + 1 : null).filter(x => x);
  return "<details class=sec open><summary>Selected classes &middot; " + kept.length + " of " + sel.flags.length + " kept</summary>" +
    "<p class=note>From " + esc(sel.parent) + " (iteration " + hist[idx].iter + "): class " + kept.join(", ") + "</p>" +
    "<div id=selCards>" + classCards(hist, idx, info.class_thumbs, sel.flags) + "</div></details>";
}}
function paintSelection(info) {{
  const sel = info.selection, hist = JOBS[sel.parent].classes, e = hist[hist.length - 1];
  fetch("/class-thumbs?job=" + encodeURIComponent(sel.parent) + "&it=" + e.iter + "&size=80").then(r => r.json()).then(j => {{
    const el = document.getElementById("selCards");
    if (el) el.innerHTML = classCards(hist, hist.length - 1, j.thumbs || [], sel.flags);
  }}).catch(() => {{}});
}}

// Collapsed-or-open section: class cards for the chosen iteration (slider),
// a convergence chart, and every class's share over the iterations overlaid.
function classesBlock(job, hist, thumbs) {{
  if (!hist || !hist.length) return "";
  const last = hist[hist.length - 1];
  classCtx = {{job: job, hist: hist, thumbs: thumbs, idx: hist.length - 1}};
  const slider = hist.length > 1 ?
    "<div style='display:flex;align-items:center;gap:8px;margin:4px 0 8px'><input type=range min=0 max=" + (hist.length - 1) +
    " value=" + (hist.length - 1) + " style='flex:1' oninput='setClassIter(+this.value)'><span id=classIterLabel class=note>iteration " + last.iter + "</span></div>" : "<span id=classIterLabel hidden></span>";
  const cards = "<div id=classCards>" + classCards(hist, hist.length - 1, thumbs, null, job) + "</div>";
  // it0 is the untrained start (switch rate is meaningless there) -- skip it.
  const ch = hist.filter(h => h.changes_classes !== null && h.iter > 0);
  const W = 480, H = 150, L = 40, B = 18, T = 8, R = 8, axis = "var(--text-muted)";
  function chart(title, series, ymax, yfmt, mark) {{
    const its = hist.filter(h => h.iter > 0), n = its.length;
    const X = k => L + k * (W - L - R) / Math.max(n - 1, 1), Y = v => T + (1 - v / ymax) * (H - T - B);
    let g = "<p class=note style='margin:10px 0 2px'>" + title + "</p><svg width=" + W + " height=" + H + " style='font-size:10px'>" +
      "<line x1=" + L + " y1=" + (H - B) + " x2=" + (W - R) + " y2=" + (H - B) + " stroke='" + axis + "'/>" +
      "<line x1=" + L + " y1=" + T + " x2=" + L + " y2=" + (H - B) + " stroke='" + axis + "'/>" +
      "<text x=" + (L - 4) + " y=" + (H - B) + " text-anchor=end fill='" + axis + "'>0</text>" +
      "<text x=" + (L - 4) + " y=" + (T + 8) + " text-anchor=end fill='" + axis + "'>" + yfmt(ymax) + "</text>" +
      "<text x=" + L + " y=" + (H - 4) + " fill='" + axis + "'>it" + its[0].iter + "</text>" +
      "<text x=" + (W - R) + " y=" + (H - 4) + " text-anchor=end fill='" + axis + "'>it" + its[n - 1].iter + "</text>";
    if (mark !== null) g += "<line x1=" + L + " y1=" + Y(mark).toFixed(1) + " x2=" + (W - R) + " y2=" + Y(mark).toFixed(1) +
      " stroke='" + axis + "' stroke-dasharray='3 3'/><text x=" + (W - R) + " y=" + (Y(mark) - 2).toFixed(1) +
      " text-anchor=end fill='" + axis + "'>" + yfmt(mark) + "</text>";
    for (const [color, vals] of series) {{
      g += "<polyline fill=none stroke='" + color + "' stroke-width=2 points='" +
        vals.map((v, k) => X(k).toFixed(1) + "," + Y(v).toFixed(1)).join(" ") + "'/>";
    }}
    return g + "</svg>";
  }}
  let conv = "";
  if (ch.length > 1) {{
    const ymax = Math.max(SETTLED * 1.2, ...ch.map(x => x.changes_classes)) * 1.1;
    const adv = JOBS[job].advice;
    if (adv && !adv.converged) conv += "<p style='margin:10px 0 0;color:#e65100;font-size:12px'><b>" + esc(adv.message) + "</b></p>";
    conv += chart("Convergence: " + (ch[ch.length - 1].changes_classes * 100).toFixed(1) +
      "% of particles switched class in iteration " + ch[ch.length - 1].iter + " (dashed = " + (SETTLED * 100) + "%, settled)",
      [["var(--accent)", ch.map(x => x.changes_classes)]], ymax, v => (v * 100).toFixed(0) + "%", SETTLED);
    // every class's share over the iterations, overlaid in one chart
    const its = hist.filter(h => h.iter > 0);
    conv += chart("Class share per iteration (all classes overlaid)",
      last.shares.map((_, i) => [CLASS_COLORS[i % CLASS_COLORS.length], its.map(h => h.shares[i] || 0)]),
      Math.max(0.1, ...its.flatMap(h => h.shares)) * 1.1, v => (v * 100).toFixed(0) + "%", null);
  }}
  return "<details class=sec open><summary>Classes</summary>" + slider + cards + conv + "</details>";
}}

function selectJob(job) {{
  pinned = job;
  highlight(job);
  try {{ history.replaceState(null, "", "#" + encodeURIComponent(job)); }} catch (e) {{}}
  document.querySelectorAll(".job-item").forEach(el => {{
    el.classList.toggle("selected", el.dataset.job === job);
  }});

  const info = JOBS[job];
  const detail = document.getElementById("detail");
  const chips = [];
  if (info.latest) chips.push("<span class=chip>&#9733; latest result</span>");
  if (info.best) chips.push("<span class=chip>&#9733; best resolution</span>");
  chips.push("<span class=chip>" + esc(info.state) + "</span>");
  if (info.resolution_angstrom) chips.push("<span class=chip>" + info.resolution_angstrom.toFixed(1) + " &Aring;</span>");
  if (info.n_particles) chips.push("<span class=chip>" + info.n_particles.toLocaleString('en-US') + " particles</span>");
  const runtime = formatDuration(info.runtime_seconds);
  if (runtime) chips.push("<span class=chip>" + runtime + "</span>");
  const optKeys = Object.keys(info.options).sort();
  const optRows = optKeys.map(k => "<tr><td class=key>" + esc(k) + "</td><td>" + esc(info.options[k]) + "</td></tr>").join("");
  const q = job.replace(/'/g, "\\\\'");
  detail.innerHTML = "<button class='close-btn' onclick='closeDrawers()'>&times;</button>" +
    "<h2>" + esc(info.alias || job) + "</h2>" + (info.alias ? "<p class=note style='margin:-8px 0 8px'>" + esc(job) + "</p>" : "") +
    (document.getElementById("card-" + job) ? "<div class=pathbtns><button class=pa-btn onclick=\\"setPath('A','" + q + "')\\">&#9679; Path A</button>" +
      "<button class=pb-btn onclick=\\"setPath('B','" + q + "')\\">&#9679; Path B (compare)</button></div>" : "") +
    "<div class=chips>" + chips.join("") + "</div>" +
    (info.annotations.length ? "<details class=sec open><summary>Notes from tools</summary>" + info.annotations.map(a =>
      "<p style='margin:6px 0'><span class='lvl-dot lvl-" + a.level + "'></span><b>" + esc(a.label) + "</b> <span class=note>" + esc(a.source) + "</span>" +
      (a.detail ? "<br><span style='font-size:12px'>" + esc(a.detail) + "</span>" : "") + "</p>").join("") + "</details>" : "") +
    (info.notes ? "<details class=sec open><summary>Notes</summary><p style='white-space:pre-wrap;margin:4px 0'>" + esc(info.notes) + "</p></details>" : "") +
    classesBlock(job, info.classes, info.class_thumbs) + selectionBlock(info) +
    "<details class=sec open><summary>Lineage</summary>" +
    "<p class=note>Parents: " + (info.parents.map(esc).join(", ") || "(none)") + "</p>" +
    "<button class='why-btn' onclick=\\"showWhy('" + q + "')\\">What changed vs. parent job? &rarr;</button></details>" +
    "<details class=sec><summary>Parameters (" + optKeys.length + ")</summary><table>" + optRows + "</table></details>";
  if (INTERACTIVE && info.classes && info.classes.length) setClassIter(info.classes.length - 1);
  if (INTERACTIVE && info.selection) paintSelection(info);
  openDrawer("detail");
  centerOn(job);
}}

const typeFilterEl = document.getElementById("typeFilter");
for (const t of Array.from(new Set(Object.keys(JOBS).map(jobType))).sort()) {{
  const opt = document.createElement("option");
  opt.value = t; opt.textContent = t;
  typeFilterEl.appendChild(opt);
}}

// Auto-refresh reloads the whole page (simplest way to pick up new jobs
// on both a static file:// export and this server, per the docstring
// above) -- that would otherwise silently reset any filter/scroll the
// user had set, which reads as "my selection keeps jumping back". Persist
// across reloads in sessionStorage (survives the reload, not a new tab).
const jobFilterEl = document.getElementById("jobFilter");
const stateFilterEl = document.getElementById("stateFilter");
const convFilterEl = document.getElementById("convFilter");
try {{
  convFilterEl.value = sessionStorage.getItem("reliontree.convFilter") || "";
  jobFilterEl.value = sessionStorage.getItem("reliontree.jobFilter") || "";
  typeFilterEl.value = sessionStorage.getItem("reliontree.typeFilter") || "";
  stateFilterEl.value = sessionStorage.getItem("reliontree.stateFilter") || "";
}} catch (e) {{}}

function onFilterChange() {{
  try {{
    sessionStorage.setItem("reliontree.jobFilter", jobFilterEl.value);
    sessionStorage.setItem("reliontree.typeFilter", typeFilterEl.value);
    sessionStorage.setItem("reliontree.stateFilter", stateFilterEl.value);
    sessionStorage.setItem("reliontree.convFilter", convFilterEl.value);
  }} catch (e) {{}}
  renderJobList(jobFilterEl.value);
}}
jobFilterEl.addEventListener("input", onFilterChange);
typeFilterEl.addEventListener("change", onFilterChange);
stateFilterEl.addEventListener("change", onFilterChange);
convFilterEl.addEventListener("change", onFilterChange);
renderJobList(jobFilterEl.value);

try {{
  if (sessionStorage.getItem("reliontree.view") === "table") toggleView();
}} catch (e) {{}}

try {{
  const savedScroll = sessionStorage.getItem("reliontree.sidebarScroll");
  if (savedScroll) document.getElementById("sidebar").scrollTop = parseInt(savedScroll, 10);
  document.getElementById("sidebar").addEventListener("scroll", e => {{
    try {{ sessionStorage.setItem("reliontree.sidebarScroll", e.target.scrollTop); }} catch (err) {{}}
  }});
}} catch (e) {{}}

const AUTO_REFRESH_SECONDS = {auto_refresh_seconds};
if (AUTO_REFRESH_SECONDS > 0) {{
  const toggle = document.getElementById("autoRefreshToggle");
  setInterval(() => {{
    // Skip a reload while the detail drawer is open (Compare, "Why this
    // job?", or plain job details) -- location.reload() would otherwise
    // wipe out whatever you're in the middle of comparing/reading.
    const detailOpen = document.getElementById("detail").classList.contains("open");
    if (toggle.checked && !detailOpen) location.reload();
  }}, AUTO_REFRESH_SECONDS * 1000);
}}

document.querySelectorAll(".job-card").forEach(el => {{
  el.style.cursor = "pointer";
  el.addEventListener("click", () => {{ if (!dragged) selectJob(el.dataset.job); }});
  el.addEventListener("mouseenter", () => highlight(el.dataset.job));
  el.addEventListener("mouseleave", () => highlight(pinned));
}});

// Deep link: #Class3D/job004 opens that job's drawer.
document.querySelectorAll(".mask-chip").forEach(el => el.addEventListener("click", e => {{ e.stopPropagation(); selectJob(el.dataset.job); }}));
{view_js}
restorePaths();
try {{
  const hashJob = decodeURIComponent(location.hash.slice(1));
  if (hashJob && JOBS[hashJob]) selectJob(hashJob);
}} catch (e) {{}}

// "updated 12 s ago" -- the page is a snapshot (auto-refresh reloads it).
const loadedAt = Date.now();
function tickUpdated() {{
  const s = Math.round((Date.now() - loadedAt) / 1000);
  const running = Object.keys(JOBS).filter(j => JOBS[j].state === "running").length;
  document.getElementById("updated").textContent = "updated " + (s < 60 ? s + " s" : Math.round(s / 60) + " min") + " ago" +
    (running ? " \u00b7 " + running + " running" : "");
}}
tickUpdated();
setInterval(tickUpdated, 1000);
</script>
</body>
</html>
"""


_NO_BROWSE_PANEL = """<div id="browse" class="drawer">
<button class="close-btn" onclick="closeDrawers()">&times;</button>
<h3>Project</h3>
<p class="note">Directory switching needs a local server —
run <code>reliontree watch</code> instead of a static export.</p></div>"""


_EXPERIMENT_NAMES = {"sta": "STA \u00b7 subtomogram averaging", "spa": "SPA \u00b7 single particle"}


def _experiment_badge(experiment):
    """Small badge next to the project name: what kind of project this is, with the evidence as tooltip."""
    if not experiment or experiment.get("type") not in _EXPERIMENT_NAMES:
        return ""
    return ' <span class="exp-badge" title="detected from: %s">%s</span>' % (
        html.escape(experiment.get("evidence", "")), _EXPERIMENT_NAMES[experiment["type"]])


def _js(obj):
    """JSON for embedding inside a <script> block: `</script>` in a job note,
    alias or tool annotation must not be able to end the block."""
    return json.dumps(obj).replace("</", "<\\/")


def render_html(tree, title="RELION job tree", refresh_seconds=None, browse_html=None,
                 selected_job=None, interactive=False):
    """A single self-contained HTML string embedding the SVG tree plus a
    click-to-browse sidebar: a filterable job list and a detail panel
    (state, resolution, particle count, parents, job options) driven by
    plain data already computed in `tree`; an export toolbar (SVG/PNG/CSV/
    JSON, all generated client-side, no round trip) with a manual "Update
    now" button (`location.reload()` — works identically for a static
    `file://` page and a `watch`-mode one) and, when `refresh_seconds` is
    set, an auto-refresh checkbox driven by `setInterval` (replaces the old
    unconditional `<meta refresh>`, which couldn't be turned off and lost
    the current `?browse=` query on reload); and, when `browse_html` is
    supplied (only `cmd_watch` does — it needs a live server to list
    directories), a right-hand project/file-browser panel. When
    `interactive` (only `cmd_watch` sets it), the detail panel gets a
    "Build tree from this job" action that navigates to `?job=...` — the
    same "show me the lineage of just this job" idea as InstantMap's job
    picker, as a link instead of a Qt dialog; `selected_job`, if set, shows
    a banner naming the current scope with a link back to the full tree.
    No framework, just a couple of `<script>` blocks of vanilla JS."""
    if refresh_seconds:
        auto_refresh_toggle = (
            '<label><input type="checkbox" id="autoRefreshToggle" checked> '
            'Auto-refresh (%ds)</label>' % refresh_seconds
        )
    else:
        auto_refresh_toggle = ""
    if selected_job:
        scope_banner = (
            '<p style="font-size:12px;color:var(--text-muted);margin:0 0 12px 0;">'
            'Showing upstream lineage of <b>%s</b> — <a href="/?job=">show full tree</a></p>' %
            html.escape(selected_job)
        )
    else:
        scope_banner = ""
    jobs = {}
    for job in sorted(ordered_jobs(tree), key=lambda j: (int(j.rsplit("job", 1)[-1]) if j.rsplit("job", 1)[-1].isdigit() else 0, j)):  # chronological
        artifacts = tree["artifacts"].get(job, {})
        stats = tree["stats"].get(job, {})
        thumb_job = tree["selection"][job]["parent"] if job in tree["selection"] else job
        jobs[job] = {
            "state": artifacts.get("state", "unknown"),
            "alias": tree["alias"].get(job, ""),
            "notes": tree["notes"].get(job, ""),
            "latest": job == tree["latest"], "best": job == tree["best"],
            "main": job in tree["main"], "side": job in tree["side"],
            "chips": tree["chips"].get(job, []),
            "annotations": tree.get("annotations", {}).get(job, []),
            "resolution_angstrom": stats.get("resolution_angstrom"),
            "n_particles": stats.get("n_particles"),
            "runtime_seconds": stats.get("runtime_seconds"),
            "parents": sorted(tree["parents"].get(job, [])),
            "options": tree["options"].get(job, {}),
            "selection": tree["selection"].get(job),
            "chosen": tree["chosen"].get(job, {}),
            "advice": class_advice(tree["classes"].get(job, [])),
            "class_thumbs": [] if interactive else (
                class_iter_thumbs(tree["job_dirs"][thumb_job], tree["classes"][thumb_job][-1]["iter"], 80,
                                  only=pick_classes(tree, thumb_job))
                if tree["classes"].get(thumb_job) else []),
            "classes": tree["classes"].get(job, []),
        }
    rows = history_rows(ordered_jobs(tree), tree["artifacts"], tree["parents"], tree["stats"])
    type_colors = {
        job: JOB_TYPE_COLORS.get(job_type(job), DEFAULT_TYPE_COLOR)
        for job in ordered_jobs(tree)
    }
    return _PAGE.format(
        experiment_badge=_experiment_badge(tree.get("experiment")),
        title=html.escape(title), title_short=html.escape(title.rstrip("/").split("/")[-1] or title), theme_css=THEME_CSS, svg=render_svg(tree, fit=True),
        jobs_json=_js(jobs), csv_json=_js(rows_to_csv(rows)),
        browse_panel=browse_html if browse_html is not None else _NO_BROWSE_PANEL,
        auto_refresh_toggle=auto_refresh_toggle,
        auto_refresh_seconds=refresh_seconds or 0,
        scope_banner=scope_banner,
        interactive_json=json.dumps(bool(interactive)),
        view_css=VIEW_CSS, view_js=VIEW_JS,
        settled=SETTLED_CHANGES, tiny=TINY_SHARE,
        type_colors_json=_js(type_colors),
    )
