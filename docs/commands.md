# Command reference

All commands take the project directory as first argument (default: found from the current directory).

| Command | Purpose |
|---|---|
| `reliontree` / `watch` | live local view in the browser |
| `tree` | job lineage as text, JSON, SVG or HTML |
| `table` | job history as CSV or Markdown |
| `methods` | draft methods paragraph |
| `diff --job A --job B [...]` | compare recorded options |
| `compare --job A --job B [...]` | options + resolution/particles/maps + class overlap in one call |
| `overlap A B` | particle overlap between two classification jobs |
| `why --job X` | why a job exists |
| `maps --job X` | the maps a job holds |
| `open --job X [--map label] [--template name]` | open maps in the one ChimeraX window |
| `settings [--chimerax ..] [--run-first ..] [--template ..] [--check]` | how ChimeraX is started |
| `analyze` | optional relion-origin checks shown on the cards |
| `plan plan.json [--apply]` | new jobs from a plan file; dry run unless `--apply` |
| `mcp` | read-only MCP server for AI assistants |
| `listener-path` | path of the ChimeraX listener script |

Details of `tree`, `table`, `methods`, `diff`, `why` and `watch` follow below. See also
[Comparing jobs](compare.md), [ChimeraX and 3D](chimerax.md) and [Scripts and AI assistants](ai.md).

## In detail

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

### `diff` — compare 2+ jobs' recorded options

```bash
reliontree diff --job Refine3D/job039 --job Refine3D/job042
reliontree diff --job Refine3D/job039 --job Refine3D/job040 --job Refine3D/job041 --format json
```

Exactly 2 `--job` values gives a changed/unchanged split; 3 or more gives a
varying/constant split across all of them at once — e.g. three Refine3D
jobs that share a Select job as input, run with different mask diameters.

### `why` — why does this job exist?

```bash
reliontree why --job Refine3D/job042
```

Its parent(s), its siblings (other jobs sharing a parent), and — when the
parent is the same job type (e.g. Refine3D from Refine3D, not Refine3D
from its Select input) — what changed in its options compared to the
parent's, since a diff against a differently-typed parent is mostly noise.
Both `diff` and `why` are also available live in the browser: check 2+
jobs in the sidebar for "Compare", or open a job's Details drawer for
"Why this job?" — computed client-side from data already on the page.

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

