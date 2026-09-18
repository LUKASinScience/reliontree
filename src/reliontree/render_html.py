"""Wrap the dependency-free SVG job-tree render in a minimal self-contained
HTML page. No JS framework, no server required — opens directly via
`file://` in any browser. Pure stdlib."""

import html
import json

from .relion_treebuild import render_svg, ordered_jobs, job_type, JOB_TYPE_COLORS, DEFAULT_TYPE_COLOR
from .relion_export import history_rows, rows_to_csv

_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>reliontree — {title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: sans-serif; background: #fafafa; display: flex; height: 100vh; }}
  h1 {{ font-size: 14px; color: #444; margin: 0 0 12px 0; word-break: break-all; }}
  #sidebar {{ width: 240px; flex: none; overflow-y: auto; border-right: 1px solid #ddd;
              background: white; padding: 12px 0; }}
  #sidebar input {{ width: calc(100% - 24px); margin: 0 12px 8px; padding: 6px; box-sizing: border-box; }}
  .job-item {{ display: flex; align-items: center; justify-content: space-between; gap: 6px;
               padding: 6px 12px; cursor: pointer; font-size: 12px; border-left: 3px solid transparent; }}
  .job-item:hover {{ background: #f0f0f0; }}
  .job-item.selected {{ background: #e8f0fe; font-weight: bold; }}
  .job-item .job-label {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .job-item .tree-btn {{ flex: none; font-size: 11px; padding: 1px 6px; border: 1px solid #ccc;
                          border-radius: 4px; background: white; cursor: pointer; color: #333; }}
  .job-item .tree-btn:hover {{ background: #e8f0fe; }}
  #main {{ flex: 1; overflow: auto; padding: 24px; }}
  .wrap {{ overflow: auto; border: 1px solid #ddd; background: white; border-radius: 8px; padding: 12px; }}
  .job-card {{ cursor: pointer; }}
  #toolbar {{ margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }}
  #toolbar button {{ font-size: 12px; padding: 5px 10px; border: 1px solid #ccc; border-radius: 5px;
                      background: white; cursor: pointer; }}
  #toolbar button:hover {{ background: #f0f0f0; }}
  #toolbar label {{ font-size: 12px; color: #555; display: flex; align-items: center; gap: 4px; margin-left: 8px; }}

  /* Both side panels are the same kind of thing: a slide-in drawer fixed to
     the right edge, opened by a toolbar button, one at a time. Neither
     reserves permanent layout width the way the old always-on #browse
     sidebar did. */
  .drawer {{ position: fixed; top: 0; right: 0; height: 100vh; width: 320px;
             background: white; border-left: 1px solid #ddd; box-shadow: -4px 0 12px rgba(0,0,0,0.08);
             padding: 16px; font-size: 13px; overflow-y: auto;
             transform: translateX(100%); transition: transform 0.15s ease; z-index: 20; }}
  .drawer.open {{ transform: translateX(0); }}
  .drawer h2, .drawer h3 {{ margin: 0 0 12px 0; font-size: 15px; }}
  .drawer .close-btn {{ float: right; border: none; background: none; font-size: 16px;
                         cursor: pointer; color: #888; line-height: 1; }}
  .drawer .close-btn:hover {{ color: #222; }}
  .drawer table {{ border-collapse: collapse; width: 100%; }}
  .drawer td {{ padding: 3px 8px 3px 0; vertical-align: top; font-size: 12px; }}
  .drawer td.key {{ color: #666; white-space: nowrap; }}
  .drawer .path {{ word-break: break-all; color: #444; margin-bottom: 10px; font-size: 12px; }}
  .drawer .note {{ color: #888; font-style: italic; font-size: 12px; }}
  .drawer button.nav {{ display: block; width: 100%; text-align: left; margin-bottom: 4px;
                         padding: 6px 8px; border: 1px solid #eee; border-radius: 5px;
                         background: white; cursor: pointer; font-size: 12px; color: #1565c0; }}
  .drawer button.nav:hover {{ background: #f0f6ff; }}
  .drawer button.nav.open-project {{ color: #fff; background: #1565c0; border-color: #1565c0; font-weight: bold; }}
  .drawer button.nav.open-project:hover {{ background: #0d47a1; }}
</style>
</head>
<body>
<div id="sidebar">
  <input id="jobFilter" type="text" placeholder="filter jobs...">
  <div id="jobList"></div>
</div>
<div id="main">
<h1>{title}</h1>
<div id="toolbar">
  <button onclick="exportSvg()">Export SVG</button>
  <button onclick="exportPng()">Export PNG</button>
  <button onclick="exportCsv()">Export CSV</button>
  <button onclick="exportJson()">Export JSON</button>
  <button onclick="location.reload()">&#8635; Update now</button>
  {auto_refresh_toggle}
  <button onclick="openDrawer('browse')" style="margin-left:auto">&#128194; Browse project</button>
</div>
{scope_banner}
<div class="wrap">
{svg}
</div>
</div>
<div id="detail" class="drawer"></div>
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
  return new XMLSerializer().serializeToString(document.querySelector(".wrap svg"));
}}

function exportSvg() {{
  download("tree.svg", svgSource(), "image/svg+xml");
}}

function exportPng() {{
  const svg = document.querySelector(".wrap svg");
  const w = svg.width.baseVal.value, h = svg.height.baseVal.value;
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

function exportCsv() {{
  download("jobs.csv", CSV_TEXT, "text/csv");
}}

function exportJson() {{
  download("jobs.json", JSON.stringify(JOBS, null, 2), "application/json");
}}

function esc(s) {{
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}}

function openDrawer(id) {{
  document.querySelectorAll(".drawer").forEach(el => el.classList.toggle("open", el.id === id));
}}

function closeDrawers() {{
  document.querySelectorAll(".drawer").forEach(el => el.classList.remove("open"));
}}

function renderJobList(filter) {{
  const list = document.getElementById("jobList");
  list.innerHTML = "";
  for (const job of Object.keys(JOBS)) {{
    if (filter && job.toLowerCase().indexOf(filter.toLowerCase()) === -1) continue;
    const div = document.createElement("div");
    div.className = "job-item";
    div.dataset.job = job;
    div.style.borderLeftColor = TYPE_COLORS[job] || "#616161";
    const label = document.createElement("span");
    label.className = "job-label";
    label.textContent = job + "  [" + JOBS[job].state + "]";
    div.appendChild(label);
    div.onclick = () => selectJob(job);
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
    list.appendChild(div);
  }}
}}

function selectJob(job) {{
  document.querySelectorAll(".job-item").forEach(el => {{
    el.classList.toggle("selected", el.dataset.job === job);
  }});
  const card = document.getElementById("card-" + CSS.escape(job));
  if (card) card.scrollIntoView({{behavior: "smooth", block: "center", inline: "center"}});

  const info = JOBS[job];
  const detail = document.getElementById("detail");
  let rows = "";
  rows += "<tr><td class=key>state</td><td>" + esc(info.state) + "</td></tr>";
  if (info.resolution_angstrom) rows += "<tr><td class=key>resolution</td><td>" + info.resolution_angstrom.toFixed(1) + " &Aring;</td></tr>";
  if (info.n_particles) rows += "<tr><td class=key>particles</td><td>" + info.n_particles.toLocaleString() + "</td></tr>";
  if (info.parents.length) rows += "<tr><td class=key>parents</td><td>" + info.parents.map(esc).join(", ") + "</td></tr>";
  for (const k of Object.keys(info.options).sort()) {{
    rows += "<tr><td class=key>" + esc(k) + "</td><td>" + esc(info.options[k]) + "</td></tr>";
  }}
  detail.innerHTML = "<button class='close-btn' onclick='closeDrawers()'>&times;</button>" +
    "<h2>" + esc(job) + "</h2><table>" + rows + "</table>";
  openDrawer("detail");
}}

document.getElementById("jobFilter").addEventListener("input", e => renderJobList(e.target.value));
renderJobList("");

const AUTO_REFRESH_SECONDS = {auto_refresh_seconds};
if (AUTO_REFRESH_SECONDS > 0) {{
  const toggle = document.getElementById("autoRefreshToggle");
  setInterval(() => {{ if (toggle.checked) location.reload(); }}, AUTO_REFRESH_SECONDS * 1000);
}}

document.querySelectorAll(".job-card").forEach(el => {{
  el.style.cursor = "pointer";
  el.addEventListener("click", () => selectJob(el.dataset.job));
}});
</script>
</body>
</html>
"""


_NO_BROWSE_PANEL = """<div id="browse" class="drawer">
<button class="close-btn" onclick="closeDrawers()">&times;</button>
<h3>Project</h3>
<p class="note">Directory switching needs a local server —
run <code>reliontree watch</code> instead of a static export.</p></div>"""


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
            '<p style="font-size:12px;color:#555;margin:0 0 12px 0;">'
            'Showing upstream lineage of <b>%s</b> — <a href="/?job=">show full tree</a></p>' %
            html.escape(selected_job)
        )
    else:
        scope_banner = ""
    jobs = {}
    for job in ordered_jobs(tree):
        artifacts = tree["artifacts"].get(job, {})
        stats = tree["stats"].get(job, {})
        jobs[job] = {
            "state": artifacts.get("state", "unknown"),
            "resolution_angstrom": stats.get("resolution_angstrom"),
            "n_particles": stats.get("n_particles"),
            "parents": sorted(tree["parents"].get(job, [])),
            "options": tree["options"].get(job, {}),
        }
    rows = history_rows(ordered_jobs(tree), tree["artifacts"], tree["parents"], tree["stats"])
    type_colors = {
        job: JOB_TYPE_COLORS.get(job_type(job), DEFAULT_TYPE_COLOR)
        for job in ordered_jobs(tree)
    }
    return _PAGE.format(
        title=title, svg=render_svg(tree),
        jobs_json=json.dumps(jobs), csv_json=json.dumps(rows_to_csv(rows)),
        browse_panel=browse_html if browse_html is not None else _NO_BROWSE_PANEL,
        auto_refresh_toggle=auto_refresh_toggle,
        auto_refresh_seconds=refresh_seconds or 0,
        scope_banner=scope_banner,
        interactive_json=json.dumps(bool(interactive)),
        type_colors_json=json.dumps(type_colors),
    )
