#!/usr/bin/env python3
"""reliontree — standalone RELION job-lineage viewer. No ChimeraX, no Qt, no
third-party dependencies (pure stdlib). Usable by a human in a terminal, by a
script/AI agent (--format json, defined exit codes), or as a zero-config
"GUI" (no arguments: auto-detects the project in the current directory and
opens an interactive-free but readable HTML tree in the browser).

    reliontree                                   # zero-config: detect + open in browser
    reliontree tree /path/to/project -o tree.svg
    reliontree tree /path/to/project --job Class3D/job012 --format json
    reliontree table /path/to/project --format csv -o jobs.csv
    reliontree methods /path/to/project
    reliontree watch /path/to/project            # live-refreshing local view, stdlib http.server only

Exit codes: 0 ok, 1 no RELION project found, 2 parse/job-lookup error.
"""

import argparse
import html
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .relion_treebuild import build_tree, ordered_jobs, render_svg
from .relion_export import history_rows, rows_to_csv, rows_to_markdown
from .relion_methods import draft_methods_paragraph
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


def cmd_watch(args):
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

    class Handler(BaseHTTPRequestHandler):
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
                page = render_html(tree, title=str(state["project"]),
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

        def log_message(self, format, *a):
            pass  # keep stdout clean; errors still surface via the page

    url = "http://127.0.0.1:%d/" % args.port
    print("reliontree watch: %s (refreshing every %ds, Ctrl-C to stop)" % (url, args.interval))
    if not args.no_open:
        webbrowser.open(url)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


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
        port=8710, interval=10, no_open=False,
    )
    cmd_watch(args)


_SUBCOMMANDS = {"tree", "table", "methods", "watch"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # `reliontree /path/to/project` (no subcommand) — the same zero-config
    # `watch` view as bare `reliontree`, just pointed at an explicit
    # directory instead of auto-detecting from cwd. argparse's subparsers
    # can't cleanly accept "either a subcommand name or a bare path" as the
    # first token, so it's sniffed here instead of fighting argparse for it.
    if argv and argv[0] not in _SUBCOMMANDS and not argv[0].startswith("-"):
        _default(project=argv[0])
        return

    p = argparse.ArgumentParser(prog="reliontree", description=__doc__.splitlines()[0])
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

    sp = sub.add_parser("watch", help="live-refreshing local view (stdlib http.server, no Flask/Streamlit)")
    sp.add_argument("project", nargs="?", help="RELION project directory (default: auto-detect from cwd)")
    sp.add_argument("--job", help="restrict to this job's upstream lineage")
    sp.add_argument("--max-hops", type=int, default=None)
    sp.add_argument("--port", type=int, default=8710)
    sp.add_argument("--interval", type=int, default=10, help="browser auto-refresh interval in seconds")
    sp.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    sp.set_defaults(func=cmd_watch)

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
