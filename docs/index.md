# reliontree

Standalone RELION job-lineage viewer. No ChimeraX, no third-party server
framework, no GUI toolkit — the default path is a self-starting stdlib-only
local server. Same single command on a workstation, an HPC login node (no
X11, no root), or a cloud VM.

## Install and run

```bash
uvx reliontree
```

No `uv`? `pipx run reliontree` works the same way — both run reliontree in
an isolated environment with nothing left behind. For a persistent
installation in an existing environment:

```bash
pip install reliontree
```

## Zero-config

```bash
reliontree
reliontree /path/to/project    # same, pointed at an explicit directory
```

Run from inside (or under) a RELION project directory. With no arguments,
reliontree walks upward looking for `default_pipeline.star` — the same way
`git status` finds its repository — and opens a live local view in your
browser: job cards with map/mask thumbnails, a click-to-browse sidebar, and
an in-page directory picker to switch projects. If no project is found at
all, it still starts and lets you browse to one instead of exiting with an
error.

<!-- TODO(Serhat): screenshots + a short GIF walkthrough (job cards, sidebar,
     project picker) — see BAUPLAN.md, needs a git contributor invite first. -->
![reliontree — job tree view](assets/screenshot-tree.png)
![reliontree — live browsing demo](assets/demo.gif)

On a machine with no browser available (a cluster login node), use
`reliontree tree --format html -o tree.html` for the old single-file static
export instead — no server, just a file to `scp` back or open from a
mounted path.

## Commands

### `tree` — job lineage

```bash
reliontree tree .                              # ASCII tree in the terminal
reliontree tree . --format json                # machine-readable, for scripts/agents
reliontree tree . --format html -o tree.html   # explicit static HTML file
reliontree tree . --format svg -o tree.svg     # raw SVG only
reliontree tree . --job Class3D/job012         # just that job's upstream lineage
reliontree tree . --job Class3D/job012 --max-hops 3
```

`--format json` is the integration point for scripts or AI agents: a
structured graph (`jobs`, `parents`, `artifacts`, `stats`) instead of text to
parse, with defined exit codes (see below).

### `table` — job history as CSV/Markdown

```bash
reliontree table . --format csv -o jobs.csv
reliontree table . --format md
```

One row per job: type, state, parent(s), resolution, particle count — for a
supplementary table or a quick spreadsheet import.

### `methods` — draft methods-section paragraph

```bash
reliontree methods .
```

One line per job, assembled from each job's own recorded parameters
(`job.star`) and outcome (resolution/particle count) — a starting point to
edit, not a citation-ready paragraph.

### `watch` — live-refreshing local view, with options

```bash
reliontree watch .
```

This is what bare `reliontree` runs under the hood with its defaults; the
`watch` subcommand exposes the knobs: `--port` (default `8710`),
`--interval` (auto-refresh seconds, default `10`), `--no-open` (skip
auto-opening the browser), plus the same `--job`/`--max-hops` as `tree`. A
local server (Python's stdlib `http.server`, no Flask/Streamlit) rebuilds
the tree on every request; usable on HPC/cloud too via an SSH tunnel.

## Exit codes

For use in scripts or CI:

| Code | Meaning |
|---|---|
| `0` | ok |
| `1` | no RELION project found (no `default_pipeline.star` in the given/current directory or any parent) |
| `2` | parse or job-lookup error (e.g. `--job` names a job not in the pipeline) |

## Why not Streamlit/Dash/a desktop GUI

Every existing RELION monitoring tool needs either a running web server
([Follow_Relion_gracefully](https://github.com/dzyla/Follow_Relion_gracefully),
[CNIO_Relion_Tools](https://github.com/cryoEM-CNIO/CNIO_Relion_Tools) — both
need an open port, awkward over SSH-only cluster access) or a desktop GUI
toolkit ([himena-relion](https://github.com/hanjinliu/himena-relion) — needs
a display, no headless mode). reliontree's default is a live local view too,
but a stdlib-only `http.server` bound to `127.0.0.1` that starts itself — no
manual server to keep alive, no third-party framework. On a login node with
no browser path at all, `reliontree tree --format html -o tree.html` falls
back to the old single-file static export instead.

## Origin

The pipeline-parsing and job-tree-diagram logic here started as the
Qt/ChimeraX-free core of the
[ChimeraX-InstantMap](https://github.com/LUKASinScience/ChimeraX-InstantMap)
plugin's RELION History tab — extracted into its own package since it never
needed ChimeraX to begin with. ChimeraX-InstantMap's homepage:
[github.com/LUKASinScience/ChimeraX-InstantMap](https://github.com/LUKASinScience/ChimeraX-InstantMap).

## License

GNU Affero General Public License v3.0 (AGPL-3.0-or-later).
