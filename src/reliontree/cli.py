#!/usr/bin/env python3
"""reliontree -- standalone RELION job-lineage viewer, no ChimeraX/Qt/third-party dependencies required.

Usable by a human in a terminal, by a script/AI agent (--format json,
defined exit codes), or zero-config (no arguments: auto-detects the
project in the current directory and opens a live local view in the
browser -- see `reliontree` with no subcommand below).

    reliontree                                   # zero-config: detect + open the live view
    reliontree /path/to/project                  # same, pointed at an explicit directory
    reliontree tree /path/to/project -o tree.svg
    reliontree tree /path/to/project --job Class3D/job012 --format json
    reliontree table /path/to/project --format csv -o jobs.csv
    reliontree methods /path/to/project
    reliontree diff --job Refine3D/job039 --job Refine3D/job042
    reliontree why --job Refine3D/job042
    reliontree compare --job Refine3D/job039 --job Refine3D/job042 [--format json]
    reliontree maps --job Refine3D/job042 ; reliontree open --job Refine3D/job042 --map mask
    reliontree watch /path/to/project            # live-refreshing local view, stdlib http.server only

Exit codes (tree/table/methods/diff/why subcommands): 0 ok, 1 no RELION project found, 2 parse/job-lookup error.
"""

import argparse
import html
import json
import os
import re
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import chimerax_bridge
from .relion_treebuild import build_tree, ordered_jobs, render_svg
from .relion_classes import class_iter_thumbs, class_overlap
from .relion_maps import list_job_maps
from .relion_diff import diff_options, diff_many_options, job_context
from .relion_export import history_rows, rows_to_csv, rows_to_markdown
from .relion_methods import draft_methods_paragraph
from .relion_orientation import job_orientation
from . import relion_plan
from .relion_project import ProjectNotFoundError, find_project
from .render_html import render_html


def _write(text, out_path):
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _build(args):
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    return project, build_tree(project, selected=args.job, max_hops=args.max_hops)


def cmd_tree(args):
    project, tree = _build(args)
    jobs = ordered_jobs(tree)
    if args.format == "svg":
        _write(render_svg(tree), args.out)
    elif args.format == "html":
        html = render_html(tree, title=str(project))
        out = args.out or "tree.html"
        _write(html, out)
        if not args.out:
            webbrowser.open(Path(out).resolve().as_uri())
    elif args.format == "json":
        _write(json.dumps({
            "project": str(project),
            "jobs": jobs,
            "parents": {j: sorted(p) for j, p in tree["parents"].items()},
            "artifacts": {j: {k: (str(v) if v else v) for k, v in a.items()}
                          for j, a in tree["artifacts"].items()},
            "stats": tree["stats"],
        }, indent=2), args.out)
    else:
        lines = ["%s  [%s]" % (j, tree["artifacts"][j]["state"]) for j in jobs]
        _write("\n".join(lines), args.out)


def cmd_table(args):
    _, tree = _build(args)
    jobs = ordered_jobs(tree)
    rows = history_rows(jobs, tree["artifacts"], tree["parents"], tree["stats"])
    text = rows_to_markdown(rows) if args.format == "md" else rows_to_csv(rows)
    _write(text, args.out)


def cmd_methods(args):
    _, tree = _build(args)
    jobs = ordered_jobs(tree)
    _write(draft_methods_paragraph(jobs, tree["options"], tree["stats"]), args.out)


def cmd_diff(args):
    """Compare 2+ jobs' recorded `job.star` options: exactly 2 gives a
    changed/unchanged split, 3+ gives a varying/constant split across all
    of them (e.g. sibling Refine3D jobs under the same Select job)."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    tree = build_tree(project)
    jobs = args.job
    missing = [j for j in jobs if j not in tree["options"]]
    if missing:
        raise ValueError("job(s) not found in pipeline: %s" % ", ".join(missing))

    if len(jobs) == 2:
        result = diff_options(tree["options"][jobs[0]], tree["options"][jobs[1]])
        if args.format == "json":
            _write(json.dumps(result, indent=2), args.out)
            return
        lines = ["Comparing %s vs %s" % (jobs[0], jobs[1]), "", "Changed:"]
        for key, (a, b) in sorted(result["changed"].items()):
            lines.append("  %-30s %s -> %s" % (key, a, b))
        if not result["changed"]:
            lines.append("  (none -- identical options)")
        _write("\n".join(lines), args.out)
    else:
        result = diff_many_options({j: tree["options"][j] for j in jobs})
        if args.format == "json":
            _write(json.dumps(result, indent=2), args.out)
            return
        lines = ["Comparing %d jobs: %s" % (len(jobs), ", ".join(jobs)), "", "Varying:"]
        for key, values in sorted(result["varying"].items()):
            lines.append("  %s" % key)
            for j in jobs:
                lines.append("    %-30s %s" % (j, values.get(j)))
        if not result["varying"]:
            lines.append("  (none -- all identical)")
        _write("\n".join(lines), args.out)


def _job_summary(tree, job, project):
    """One row per job for `compare`: what the browser's compare view shows at a glance."""
    art = tree["artifacts"].get(job) or {}
    st = tree["stats"].get(job) or {}
    return {"job": job, "type": job.split("/")[0], "state": art.get("state", "unknown"),
            "parents": sorted(tree["parents"].get(job, ())), "resolution_angstrom": st.get("resolution_angstrom"),
            "n_particles": st.get("n_particles"),
            "maps": [{"label": m["label"], "files": m["files"]} for m in list_job_maps(project / job)]}


def cmd_compare(args):
    """Everything about 2+ jobs side by side: state/resolution/particles, changed options, maps, and (two
    classification jobs) the particle overlap. The command-line twin of the browser's compare view."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    tree = build_tree(project)
    jobs = args.job
    missing = [j for j in jobs if j not in tree["options"]]
    if missing:
        raise ValueError("job(s) not found in pipeline: %s" % ", ".join(missing))
    out = {"jobs": [_job_summary(tree, j, project) for j in jobs]}
    out["options"] = (diff_options(tree["options"][jobs[0]], tree["options"][jobs[1]]) if len(jobs) == 2
                      else diff_many_options({j: tree["options"][j] for j in jobs}))
    out["overlap"] = None
    if len(jobs) == 2 and all(j.split("/")[0] in ("Class2D", "Class3D") for j in jobs):
        ov = class_overlap(project / jobs[0], project / jobs[1])
        if ov is not None:
            out["overlap"] = {"classes_a": ov["classes_a"], "classes_b": ov["order_b"], "score": ov["score"],
                              "counts": {"%d,%d" % k: v for k, v in ov["counts"].items()}}
    if args.format == "json":
        _write(json.dumps(out, indent=2), args.out)
        return
    lines = ["%-26s %-10s %-10s %10s %12s  %s" % ("job", "type", "state", "res (A)", "particles", "maps")]
    for r in out["jobs"]:
        res = "%.1f" % r["resolution_angstrom"] if r["resolution_angstrom"] else "-"
        lines.append("%-26s %-10s %-10s %10s %12s  %s" % (r["job"], r["type"], r["state"], res,
                     "{:,}".format(r["n_particles"]) if r["n_particles"] else "-", ", ".join(m["label"] for m in r["maps"]) or "-"))
    lines.append("")
    if len(jobs) == 2:
        lines.append("Changed options:")
        for key, (a, b) in sorted(out["options"]["changed"].items()):
            lines.append("  %-30s %s -> %s" % (key, a, b))
        if not out["options"]["changed"]:
            lines.append("  (none -- identical options)")
    else:
        lines.append("Varying options:")
        for key, values in sorted(out["options"]["varying"].items()):
            lines.append("  %s" % key)
            for j in jobs:
                lines.append("    %-28s %s" % (j, values.get(j)))
        if not out["options"]["varying"]:
            lines.append("  (none -- all identical)")
    if out["overlap"]:
        ov = out["overlap"]
        lines += ["", "Particle overlap (rows = %s class, columns = %s class; %.0f%% on the diagonal):" % (jobs[0], jobs[1], ov["score"] * 100),
                  "      " + "".join("%8d" % b for b in ov["classes_b"])]
        for a in ov["classes_a"]:
            lines.append("%5d " % a + "".join("%8d" % ov["counts"].get("%d,%d" % (a, b), 0) for b in ov["classes_b"]))
    _write("\n".join(lines), args.out)


def cmd_maps(args):
    """The maps a job holds, as the 3D buttons group them (label + file names)."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    if not _JOB_ID.fullmatch(args.job):
        raise ValueError("bad job id %r" % args.job)
    maps = list_job_maps(project / args.job)
    if args.format == "json":
        _write(json.dumps({"job": args.job, "maps": maps}, indent=2), args.out)
        return
    _write("\n".join("%-28s %s" % (m["label"], ", ".join(m["files"])) for m in maps) or "(no maps in %s)" % args.job, args.out)


def cmd_open(args):
    """Open a job's maps in the ONE ChimeraX that reliontree talks to (starts it if none runs) -- the 3D button, from the shell.
    --map picks an entry by its label (see `reliontree maps`); default: the most important one."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    if not _JOB_ID.fullmatch(args.job):
        raise ValueError("bad job id %r" % args.job)
    maps = list_job_maps(project / args.job)
    if not maps:
        raise ValueError("no maps in %s" % args.job)
    if args.map:
        picked = [m for m in maps if args.map.lower() in m["label"].lower()]
        if not picked:
            raise ValueError("no map entry matching %r; available: %s" % (args.map, ", ".join(m["label"] for m in maps)))
        entry = picked[0]
    else:
        entry = maps[0]
    for n in entry["files"]:
        if not _MAP_FILE.fullmatch(n):
            raise ValueError("bad file name %r" % n)
    msg = chimerax_bridge.open_files([project / args.job / n for n in entry["files"]], tile=entry["tile"] and not args.no_tile,
                                     style=args.template)
    print("%s: %s" % (entry["label"], msg))


def cmd_settings(args):
    """Show the ChimeraX settings; set them with --chimerax / --run-first / --template; --check runs ChimeraX --version."""
    new = {k: v for k, v in (("chimerax_cmd", args.chimerax), ("prelaunch", args.run_first), ("figure_template", args.template)) if v is not None}
    if new:
        chimerax_bridge.save_settings(new)
    info = chimerax_bridge.describe()
    if args.check:
        ok, text = chimerax_bridge.check_settings()
        info["check"] = {"ok": ok, "text": text}
    print(json.dumps(info, indent=2))
    if args.check and not info["check"]["ok"]:
        raise SystemExit(2)


def cmd_analyze(args):
    """Run relion-origin's per-particle checks (orientation gaps, mixing beyond chance) and write them where the view
    picks them up. relion-origin is an optional companion (numpy, pandas, starfile): it is imported here and nowhere
    else, so everything else in reliontree works without it."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    try:
        from relion_origin.annotations import annotate_project, write_annotations
    except ImportError:
        raise ValueError("`reliontree analyze` needs the optional companion relion-origin, which is not installed.\n"
                         "Install relion-origin:  pip install \"git+https://github.com/LUKASinScience/relion-origin\"")
    notes, skipped = annotate_project(project)
    path = write_annotations(project, "relion-origin", notes)
    print("wrote %d job(s) with findings to %s" % (len(notes), path))
    for job, why in skipped:
        print("skipped %s: %s" % (job, why), file=sys.stderr)


def cmd_plan(args):
    """plan check (dry run, default) / plan apply (register as Scheduled, runs nothing)."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    rows = relion_plan.resolve(project, relion_plan.load(args.plan))
    lines, bad = [], False
    for r in rows:
        lines.append("%s  <- %s%s" % (r["id"], r["from"], "  alias=" + r["alias"] if r["alias"] else ""))
        for k, (a, b) in sorted(r["changed"].items()):
            lines.append("    %-28s %s -> %s" % (k, a, b))
        for e in r["errors"]:
            lines.append("    ERROR: " + e)
            bad = True
    if args.apply and not bad:
        made = relion_plan.apply(project, rows)
        lines.append("")
        lines += ["registered %s as %s (Scheduled, not started)" % (k, v) for k, v in made.items()]
        Path(args.plan).with_suffix(".applied.json").write_text(json.dumps(made, indent=2))
    elif args.apply:
        lines.append("\nnot applied: fix the errors above")
    _write("\n".join(lines), None)
    if bad:
        sys.exit(2)


def cmd_overlap(args):
    """Particle overlap between two Class2D/Class3D jobs (rows: job A's
    classes, columns: job B's), from each job's final data.star."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    result = class_overlap(project / args.job_a, project / args.job_b)
    if result is None:
        raise ValueError("both jobs need a run_data.star / run_itNNN_data.star")
    ca, cb, counts = result["classes_a"], result["order_b"], result["counts"]
    if args.format == "json":
        _write(json.dumps({"classes_a": ca, "classes_b": cb, "score": result["score"],
                           "counts": {"%d,%d" % k: v for k, v in counts.items()}}, indent=2), args.out)
        return
    lines = ["Particles: rows = %s class, columns = %s class (columns ordered best-match first; %.0f%% of particles on the diagonal)" % (args.job_a, args.job_b, result["score"] * 100),
             "      " + "".join("%8d" % b for b in cb)]
    for a in ca:
        lines.append("%5d " % a + "".join("%8d" % counts.get((a, b), 0) for b in cb))
    _write("\n".join(lines), args.out)


def cmd_why(args):
    """"Why does this job exist?": its parent(s), sibling jobs sharing a
    parent, and what changed in its options compared to its parent's."""
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    tree = build_tree(project)
    if args.job not in tree["parents"]:
        raise ValueError("job %r not found in pipeline under %s" % (args.job, project))
    ctx = job_context(tree, args.job)
    if args.format == "json":
        _write(json.dumps(ctx, indent=2), args.out)
        return
    lines = [
        "Job: %s" % args.job,
        "",
        "Parent(s): %s" % (", ".join(ctx["parents"]) or "(none)"),
        "Sibling(s): %s" % (", ".join(ctx["siblings"]) or "(none)"),
        "",
    ]
    if ctx["diff_from_parent"] is not None:
        lines.append("Changed from parent (%s):" % ctx["diff_parent"])
        changed = ctx["diff_from_parent"]["changed"]
        for key, (a, b) in sorted(changed.items()):
            lines.append("  %-30s %s -> %s" % (key, a, b))
        if not changed:
            lines.append("  (none -- identical options)")
    elif ctx["parents"]:
        lines.append(
            "(parent %s is a different job type -- options aren't comparable)" % ctx["diff_parent"]
        )
    _write("\n".join(lines), args.out)


def _nav_button(label, href, primary=False):
    cls = "nav open-project" if primary else "nav"
    return '<button type="button" class="%s" onclick="location.href=\'%s\'">%s</button>' % (
        cls, html.escape(href, quote=True), html.escape(label))


def _dir_entries_html(browse_dir, current_project=None):
    """The directory-listing part shared by the in-tree browse drawer and
    the no-project picker screen: an "open as project" button when
    `browse_dir` itself holds a default_pipeline.star, an "up" button, and
    one button per subdirectory (`*` marks RELION projects). Buttons, not
    links — one consistent clickable affordance everywhere in this UI."""
    parts = []
    if (browse_dir / "default_pipeline.star").is_file() and browse_dir != current_project:
        parts.append(_nav_button("Open this as project →", "/?open=%s" % browse_dir, primary=True))
    if browse_dir.parent != browse_dir:
        parts.append(_nav_button(".. (up)", "/?browse=%s" % browse_dir.parent))
    try:
        subdirs = sorted(p for p in browse_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        subdirs = []
    for sub in subdirs:
        marker = " *" if (sub / "default_pipeline.star").is_file() else ""
        parts.append(_nav_button(sub.name + marker, "/?browse=%s" % sub))
    return "\n".join(parts)


def _render_browse_panel(browse_dir, current_project, error=None, start_open=False):
    """The right-hand drawer's content: current project, an optional error,
    where we're browsing, and the shared directory-listing buttons.
    `start_open` renders it already expanded — used when the request itself
    was a `?browse=`/`?open=` navigation, so the drawer doesn't visibly
    snap shut on reload while you're mid-browse."""
    parts = ['<button class="close-btn" onclick="closeDrawers()">&times;</button>',
             '<h3>Project</h3>',
             '<p class="path">%s</p>' % html.escape(str(current_project))]
    if error:
        parts.append('<p class="note">%s</p>' % html.escape(error))
    parts.append('<p class="path">Browsing: %s</p>' % html.escape(str(browse_dir)))
    parts.append(_dir_entries_html(browse_dir, current_project))
    cls = "drawer open" if start_open else "drawer"
    return '<div id="browse" class="%s">\n%s\n</div>' % (cls, "\n".join(parts))


_PICKER_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>reliontree — pick a project</title>
<style>
  body {{ font-family: sans-serif; background: #fafafa; margin: 0; padding: 32px; }}
  h1 {{ font-size: 16px; color: #444; margin: 0 0 16px 0; }}
  .card {{ max-width: 640px; border: 1px solid #ddd; background: white; border-radius: 8px; padding: 20px; }}
  .path {{ word-break: break-all; color: #444; margin-bottom: 10px; font-size: 13px; }}
  .note {{ color: #888; font-style: italic; }}
  button.nav {{ display: block; width: 100%; text-align: left; margin-bottom: 4px;
                padding: 6px 8px; border: 1px solid #eee; border-radius: 5px;
                background: white; cursor: pointer; font-size: 13px; color: #1565c0; }}
  button.nav:hover {{ background: #f0f6ff; }}
  button.nav.open-project {{ color: #fff; background: #1565c0; border-color: #1565c0; font-weight: bold; }}
  button.nav.open-project:hover {{ background: #0d47a1; }}
</style>
</head>
<body>
<h1>reliontree — no RELION project selected yet</h1>
<div class="card">
{error}
<p class="path">Browsing: {browse_dir}</p>
{entries}
</div>
</body>
</html>
"""


def _render_picker_page(browse_dir, error=None):
    """Standalone start screen for when reliontree is launched with no
    project directory at all (no default_pipeline.star found upward from
    cwd) — the same browse-and-open buttons as the in-tree drawer, full
    page, so there's always something to click instead of exiting with an
    error before a project is even chosen."""
    return _PICKER_PAGE.format(
        error='<p class="note">%s</p>' % html.escape(error) if error else "",
        browse_dir=html.escape(str(browse_dir)),
        entries=_dir_entries_html(browse_dir),
    )


_JOB_ID = re.compile(r"[A-Za-z0-9_]+/job\d+")


_MAP_FILE = re.compile(r"[\w.\-]+\.(?:mrc|map|bild)", re.IGNORECASE)


def _open_3d(query, project):
    """Open map/.bild files of one job in ChimeraX. The page names files by basename only (`f=`, repeatable);
    the path is built here from a validated job id, so nothing outside the job directory can be reached."""
    try:
        job = query.get("job", [""])[0].rstrip("/")
        if not _JOB_ID.fullmatch(job):
            raise ValueError("bad job id %r" % job)
        names = query.get("f", [])
        if not names or any(not _MAP_FILE.fullmatch(n) for n in names):
            raise ValueError("bad file name")
        paths = [project / job / n for n in names]
        return {"ok": chimerax_bridge.open_files(paths, tile=query.get("tile", [""])[0] == "1")}
    except (ValueError, KeyError) as exc:
        return {"error": str(exc)}


def _api(route, query, project):
    """JSON for the page's lazy requests: per-iteration class thumbnails and
    two-job particle overlap. Job ids are matched against a strict pattern
    so a query can't point outside the project directory."""
    def job_dir(key):
        job = query.get(key, [""])[0].rstrip("/")
        if not _JOB_ID.fullmatch(job):
            raise ValueError("bad job id %r" % job)
        return project / job

    try:
        if route == "/class-thumbs":
            size = min(int(query.get("size", ["72"])[0]), 400)
            return {"thumbs": class_iter_thumbs(job_dir("job"), int(query["it"][0]), size)}
        if route == "/orientation":
            cls = query.get("cls", [""])[0]
            return job_orientation(job_dir("job"), int(cls) if cls.isdigit() else None) or {"error": "no angular distribution (angdist.bild) in this job"}
        result = class_overlap(job_dir("a"), job_dir("b"))
        if result is None:
            return {"error": "no data.star in one of the jobs"}
        return {"classes_a": result["classes_a"], "classes_b": result["classes_b"],
                "counts": {"%d,%d" % k: v for k, v in result["counts"].items()},
                "order_b": result["order_b"], "score": result["score"]}
    except (ValueError, KeyError) as exc:
        return {"error": str(exc)}


def cmd_mcp(args):
    from .mcp_server import serve
    project = Path(args.project) if getattr(args, "project", None) else find_project()
    serve(project)


def make_server(args):
    """Build (not start) the live-view server for `args` (project, port, interval, job, max_hops); returns (server, url).
    cmd_watch serves it in the foreground, `start_background` in a thread (how CryoSTAR-Base embeds it)."""
    """Stdlib-only live view: regenerates the tree HTML on every request
    (auto-refresh meta tag drives the browser reload) — no Flask/Streamlit,
    no persistent background process beyond this one server. A right-hand
    panel lets you browse the filesystem and switch the RELION project
    directory without restarting the server (plain server-rendered links,
    no AJAX/JS framework). If no project directory is given and none is
    found upward from cwd, starts anyway with a bare file-browser start
    screen instead of exiting — you can navigate to one and open it."""
    if getattr(args, "project", None):
        project = Path(args.project)
    else:
        try:
            project = find_project()
        except ProjectNotFoundError:
            project = None
    state = {"project": project}
    # Changing settings or opening ChimeraX can run a shell command on this machine, so those routes only answer
    # requests that carry this per-run token (embedded in our own page, unreadable for other sites: no CORS headers)
    # AND arrive with our own Host/Origin (blocks DNS rebinding and cross-site forms).
    page_token = secrets.token_urlsafe(16)
    own_hosts = ("127.0.0.1:%d" % args.port, "localhost:%d" % args.port)

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self, token):
            origin = self.headers.get("Origin")
            return (self.headers.get("Host", "") in own_hosts
                    and (origin is None or origin in ["http://" + h for h in own_hosts])
                    and secrets.compare_digest(str(token or ""), page_token))

        def _deny(self):
            self._json({"error": "forbidden (open this page from the reliontree server itself)"}, status=403)

        def do_POST(self):
            try:
                if urlsplit(self.path).path != "/settings":
                    self._json({"error": "not found"}, status=404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 20000 or "application/json" not in self.headers.get("Content-Type", ""):
                    self._json({"error": "expected a small JSON body"}, status=400)
                    return
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict) or not self._authorized(body.get("t")):
                    self._deny()
                    return
                try:
                    chimerax_bridge.save_settings(body)
                except ValueError as exc:
                    self._json({"error": str(exc)})
                    return
                self._json(chimerax_bridge.describe())
            except (ValueError, OSError) as exc:
                self._json({"error": str(exc)})

        def do_GET(self):
            try:
                query = parse_qs(urlsplit(self.path).query)
                error = None
                if "open" in query:
                    candidate = Path(query["open"][0]).resolve()
                    if (candidate / "default_pipeline.star").is_file():
                        state["project"] = candidate
                    else:
                        error = "not a RELION project (no default_pipeline.star): %s" % candidate
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return

                route = urlsplit(self.path).path
                if route in ("/open-3d", "/settings", "/settings-check"):
                    if not self._authorized(query.get("t", [""])[0]):
                        self._deny()
                        return
                    if route == "/settings":
                        self._json(chimerax_bridge.describe())
                    elif route == "/settings-check":
                        ok, text = chimerax_bridge.check_settings()
                        self._json({"ok": ok, "text": text})
                    elif state["project"] is not None:
                        self._json(_open_3d(query, state["project"]))
                    return
                if route in ("/class-thumbs", "/overlap", "/orientation") and state["project"] is not None:
                    self._json(_api(route, query, state["project"]))
                    return

                if state["project"] is None:
                    browse_dir = Path(query.get("browse", [str(Path.cwd())])[0])
                    body = _render_picker_page(browse_dir, error).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                browse_dir = Path(query.get("browse", [str(state["project"])])[0])
                # `?job=` (blank clears it) lets the page itself pick a job and
                # rebuild the tree scoped to just its upstream lineage — the
                # same "Show Job Tree from here" idea as InstantMap's picker,
                # just a link instead of a Qt dialog.
                selected_job = query["job"][0] if "job" in query else args.job
                selected_job = selected_job or None
                max_hops = int(query["max_hops"][0]) if query.get("max_hops", [""])[0] else args.max_hops
                try:
                    tree = build_tree(state["project"], selected=selected_job, max_hops=max_hops)
                except ValueError:
                    # stale ?job= from before a directory switch, or a typo'd
                    # job id — fall back to the full tree rather than 500ing.
                    selected_job = None
                    tree = build_tree(state["project"], selected=None, max_hops=None)
                browse_html = _render_browse_panel(browse_dir, state["project"], error,
                                                     start_open=("browse" in query or "open" in query))
                page = render_html(tree, title=str(state["project"]), token=page_token,
                                    refresh_seconds=args.interval, browse_html=browse_html,
                                    selected_job=selected_job, interactive=True)
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(exc).encode("utf-8"))

        def _json(self, payload, status=None):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status or (200 if "error" not in payload else 400))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *a):
            pass  # keep stdout clean; errors still surface via the page

    return ThreadingHTTPServer(("127.0.0.1", args.port), Handler), "http://127.0.0.1:%d/" % args.port


def cmd_watch(args):
    server, url = make_server(args)
    print("reliontree watch: %s (refreshing every %ds, Ctrl-C to stop)" % (url, args.interval))
    if not args.no_open:
        webbrowser.open(url)
    server.serve_forever()


class BackgroundServer:
    """The live view served from a thread of the calling process (no subprocess, no PATH lookup). `stop()` frees the port."""

    def __init__(self, server, url):
        import threading
        self.server, self.url = server, url
        self.thread = threading.Thread(target=server.serve_forever, name="reliontree-view", daemon=True)
        self.thread.start()

    def alive(self):
        return self.thread.is_alive()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def start_background(project, port=8710, interval=10):
    """Start the read-only live view of one RELION project in a background thread and return a BackgroundServer.
    Raises OSError if the port is busy and ValueError if `project` has no default_pipeline.star."""
    project = Path(project)
    if not (project / "default_pipeline.star").is_file():
        raise ValueError("not a RELION project (no default_pipeline.star): %s" % project)
    args = argparse.Namespace(project=str(project), job=None, max_hops=None, port=int(port), interval=interval, no_open=True)
    return BackgroundServer(*make_server(args))


def _default(project=None):
    """No subcommand: zero-config path — use `project` if given (`reliontree
    /path/to/project`), else auto-detect from cwd, else start anyway with
    the bare directory-picker start screen — and open the live `watch` view
    (browsing/switching directories, picking a job to scope the tree to,
    and auto-refresh all need the local stdlib server; a static file can't
    do any of that). Use `reliontree tree --format html -o tree.html` for
    the old dependency-free single-file export (e.g. to hand off from a
    login node with no browser/port available there)."""
    args = argparse.Namespace(
        project=project, job=None, max_hops=None,
        port=int(os.environ.get("RELIONTREE_PORT", 8710)), interval=10, no_open=False,
    )
    cmd_watch(args)


def _build_parser():
    p = argparse.ArgumentParser(
        prog="reliontree",
        description=__doc__.split("\n\n")[0],
        epilog=(
            "examples:\n"
            "  reliontree                     zero-config: detect + open the live view\n"
            "  reliontree /path/to/project    same, pointed at an explicit directory\n"
            "  reliontree tree . --format json\n"
            "  reliontree watch . --port 8710"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
        sp.add_argument("--job", help="restrict to this job's upstream lineage, e.g. Class3D/job012")
        sp.add_argument("--max-hops", type=int, default=None, help="limit upstream depth from --job")
        sp.add_argument("-o", "--out", help="output file (default: stdout, or tree.html for --format html)")

    sp = sub.add_parser("tree", help="job lineage as text/svg/html/json")
    common(sp)
    sp.add_argument("--format", choices=["text", "svg", "html", "json"], default="text")
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser("table", help="job lineage as a CSV/Markdown table")
    common(sp)
    sp.add_argument("--format", choices=["csv", "md"], default="csv")
    sp.set_defaults(func=cmd_table)

    sp = sub.add_parser("methods", help="draft methods-section paragraph")
    common(sp)
    sp.set_defaults(func=cmd_methods)

    sp = sub.add_parser("diff", help="compare 2+ jobs' recorded options (changed/varying vs. unchanged/constant)")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--job", action="append", required=True,
                     help="a job to compare, e.g. --job Refine3D/job039 --job Refine3D/job042 (repeat for 3+)")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("-o", "--out", help="output file (default: stdout)")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("compare", help="2+ jobs side by side: resolution/particles/maps, changed options, class overlap (the compare view, in the shell)")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--job", action="append", required=True, help="a job to compare; repeat for 3 or more")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("-o", "--out", help="output file (default: stdout)")
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("maps", help="the maps (and .bild files) a job holds, grouped as the 3D buttons do")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--job", required=True, help="e.g. Refine3D/job042")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("-o", "--out", help="output file (default: stdout)")
    sp.set_defaults(func=cmd_maps)

    sp = sub.add_parser("open", help="open a job's maps in ChimeraX (one window; starts it if needed), optionally with a FigureStyle template")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--job", required=True, help="e.g. Refine3D/job042")
    sp.add_argument("--map", help="part of a map entry's label, e.g. mask, half, post (see `reliontree maps`)")
    sp.add_argument("--no-tile", action="store_true", help="do not tile several maps side by side")
    sp.add_argument("--template", help="FigureStyle template to apply (default: the setting)")
    sp.set_defaults(func=cmd_open)

    sp = sub.add_parser("settings", help="show or set how ChimeraX is started (command, 'run first' snippet such as module load, FigureStyle template)")
    sp.add_argument("--chimerax", help="ChimeraX command (one line)")
    sp.add_argument("--run-first", help="shell snippet run before ChimeraX, e.g. 'module load chimerax'")
    sp.add_argument("--template", help="FigureStyle template name (empty string = none)")
    sp.add_argument("--check", action="store_true", help="run the snippet and `ChimeraX --version` (up to 60 s)")
    sp.set_defaults(func=cmd_settings)

    sp = sub.add_parser("analyze", help="run the optional relion-origin checks and show the findings as pills on the job cards")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("plan", help="plan.json -> new jobs: dry run by default, --apply registers them as Scheduled (runs nothing)")
    sp.add_argument("plan", help="plan file (JSON)")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--apply", action="store_true", help="register via relion_pipeliner --addJobFromStar")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("overlap", help="particle overlap matrix between two classification jobs")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("job_a", help="e.g. Class3D/job010")
    sp.add_argument("job_b", help="e.g. Class3D/job015")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("-o", "--out", help="output file (default: stdout)")
    sp.set_defaults(func=cmd_overlap)

    sp = sub.add_parser("why", help="why does this job exist: parent(s), siblings, and what changed from the parent")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--job", required=True, help="the job to explain, e.g. Refine3D/job042")
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("-o", "--out", help="output file (default: stdout)")
    sp.set_defaults(func=cmd_why)

    sp = sub.add_parser("watch", help="live-refreshing local view (stdlib http.server, no Flask/Streamlit)")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--job", help="restrict to this job's upstream lineage")
    sp.add_argument("--max-hops", type=int, default=None)
    sp.add_argument("--port", type=int, default=8710)
    sp.add_argument("--interval", type=int, default=10, help="browser auto-refresh interval in seconds")
    sp.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("mcp", help="read-only MCP server (stdio) over a RELION project, for AI assistants")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.set_defaults(func=cmd_mcp)

    sp = sub.add_parser("listener-path", help="print the path of the ChimeraX listener script (use: runscript <path> in a running ChimeraX)")
    sp.set_defaults(func=lambda args: print(chimerax_bridge.LISTENER_SCRIPT))

    p.subcommand_names = frozenset(sub.choices)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = _build_parser()
    subcommands = p.subcommand_names   # read from the parser: a hand-kept list drifted (plan, analyze never worked)

    # `reliontree /path/to/project` (no subcommand) — the same zero-config
    # `watch` view as bare `reliontree`, just pointed at an explicit
    # directory instead of auto-detecting from cwd. argparse's subparsers
    # can't cleanly accept "either a subcommand name or a bare path" as the
    # first token, so it's sniffed here instead of fighting argparse for it.
    if argv and argv[0] not in subcommands and not argv[0].startswith("-"):
        if not Path(argv[0]).exists():
            print("reliontree: %r is neither a command nor an existing directory (commands: %s)" % (argv[0], ", ".join(sorted(subcommands))),
                  file=sys.stderr)
            sys.exit(2)
        _default(project=argv[0])
        return

    args = p.parse_args(argv)
    try:
        if args.cmd is None:
            # zero-config: `reliontree` with no arguments at all
            _default()
        else:
            args.func(args)
    except ProjectNotFoundError as exc:
        print("reliontree: %s" % exc, file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError) as exc:
        print("reliontree: %s" % exc, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
