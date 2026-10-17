# reliontree

One job, one cheese, one relentless mouse. Welcome to reliontree  — the map of the hunt.

![the mouse's hunting journey across a job tree](docs/assets/mouse-hunt.gif)

Full guide: [lukasinscience.github.io/reliontree](https://lukasinscience.github.io/reliontree/)

## Why "reliontree"

In relion, the mouse cursor hunts down exactly one piece of cheese per
job, chasing it all the way to the end. reliontree is about the whole
job tree: the mouse's full hunting journey across every job, in one run.


Standalone RELION job-lineage viewer. No ChimeraX, no third-party server
framework, no GUI toolkit — the default path is a self-starting stdlib-only
local server. 

![reliontree — live browsing demo](docs/assets/demo.gif)


Works on a workstation, an HPC login node (no X11, no root),
or a cloud VM, with the same single command.

reliontree is not on PyPI yet, so install it straight from GitHub:

```bash
uvx --from git+https://github.com/LUKASinScience/reliontree reliontree     # isolated environment, nothing left behind
```

Run from inside (or under) a RELION project directory. Zero arguments:
detects `default_pipeline.star` and opens a live local view in your
browser — job cards with map thumbnails, click-to-browse sidebar, and a
directory picker if no project is found yet. No project directory handy?
`reliontree` still starts and lets you browse to one. On a machine with no
browser (a login node), use `reliontree tree --format html -o tree.html`
for the old single-file static export instead.

No `uv`? `pipx run --spec git+https://github.com/LUKASinScience/reliontree reliontree` works the same way.
Want it installed persistently in an existing env:
`pip install "git+https://github.com/LUKASinScience/reliontree"` (Python 3.9 or newer, no further dependencies).

![reliontree — job tree view](docs/assets/screenshot-tree.png)



## Usage

```bash
reliontree                                    # zero-config: opens the live view
reliontree /path/to/project                   # same, pointed at an explicit directory
reliontree tree . --format text               # ASCII tree in the terminal
reliontree tree . --format json               # machine-readable, for scripts/agents
reliontree tree . --job Class3D/job012        # just that job's upstream lineage
reliontree table . --format csv -o jobs.csv   # job table for a supplement
reliontree methods .                          # draft methods-paragraph, one line per job
reliontree diff --job Refine3D/job039 --job Refine3D/job042   # 2+ jobs' changed/varying options
reliontree why --job Refine3D/job042          # parent, siblings, what changed from the parent
reliontree compare --job Refine3D/job039 --job Refine3D/job042   # options + resolution/particles/maps + class overlap
reliontree maps --job Refine3D/job042         # which maps a job holds
reliontree open --job Refine3D/job042 --map mask   # open in the one ChimeraX window
reliontree settings --run-first "module load chimerax" --check
reliontree analyze                            # optional: relion-origin checks -> pills on the job cards
reliontree plan plan.json                     # dry run: new jobs as diffs against existing ones; --apply registers them as Scheduled (needs relion_pipeliner)
reliontree overlap Class3D/job008 Class3D/job009   # particle overlap matrix between two classifications
reliontree tree . --format html -o tree.html  # old single-file static export
```

In the live view: check two or more jobs in the sidebar to enable "Compare",
or open a job's Details drawer and click "Why this job?" — both run
entirely client-side against data already on the page, no server round trip.

Class2D/Class3D jobs get more in the live view: each card shows the class
averages with their share of particles (near-empty classes dimmed, classes a
Select job kept marked with a green check) and a convergence sparkline; the
drawer adds an iteration slider, convergence and class-share charts, and
a plain statement when a classification hasn't converged (how many particles still
switch class; what to do about it is relion-copilot's job). "Compare" on 2+ classifications also shows the particle
overlap heatmap between them. The sidebar can filter on convergence. The
overlap heatmap and the iteration slider need `reliontree watch` (they load
data on demand); a static `--format html` export shows the final iteration.

More in the live view:

- **Project type** (STA or SPA) is detected from the pipeline and `job.star` and shown next to the project name.
- **Aliases and notes**: RELION aliases are the card titles; notes typed into a job's `note.txt` appear in its panel.
  Jobs whose folder is missing (trimmed or deposited projects) are drawn compactly and hidden in the sidebar list.
- **Paths**: pick a result (A/B buttons, "Path to…", "★ Latest") to highlight how you got there, compare two paths,
  or show only the selection; pan and zoom with wheel/drag, 100% and Overview buttons.
- **Orientation globe**: the job panel of a Class3D/Refine3D job shows where the particles look from, read from RELION's own
  `*_angdist.bild` (no extra dependency): heat = how many particles, grey = no particles. Drag to rotate; a static
  export embeds the globe of the final refinement only.

Exit codes for the `tree`/`table`/`methods`/`diff`/`why` subcommands (for scripting):
`0` ok, `1` no RELION project found, `2`
parse/job-lookup error.

## Open maps in ChimeraX (3D buttons)

In the live view (`reliontree watch`) every job card that holds a map has a blue **3D** chip on its top-right edge, plus a
purple **Mask** chip when the job holds or uses a mask. This is not limited to classification: Refine3D, PostProcess,
MaskCreate, LocalRes, Reconstruct, InitialModel and any other job with a `.mrc`/`.map` in its folder get one. The job
detail has an **Open in ChimeraX** section with every map of the job (final map, post-processed, half maps, masks, all
classes side by side, other maps) and the angular distributions; each class card keeps its own **3D** button.

**One ChimeraX window for everything.** The first click starts ChimeraX with reliontree's own listener script (no
InstantMap needed); every later click, also while it is still starting, is handed to that same window. To use a ChimeraX
you already have open, run `runscript <path printed by "reliontree listener-path">` there (or
`instantmap listen` with the optional ChimeraX-InstantMap plugin).
ChimeraX itself is required for the 3D buttons; the InstantMap plugin is optional.

**Settings (gear button).** If `chimerax` is not on your PATH, or you are on a cluster, set how ChimeraX is started: the
command, and an optional *Run first* line such as `module load chimerax`. They are stored in `~/.reliontree/settings.json`
(owner-only) and used only when no listening ChimeraX is running. **Check** runs *Run first* and `ChimeraX --version`.
The lines run on the machine where reliontree runs, so on a cluster you need a display (for example `ssh -X`).

**Safety.** The two programs talk through a private folder (`~/.reliontree/chimerax`, owner-only); no network port is
opened on the ChimeraX side, and the listener only ever runs `open <map>` (and `tile`) for existing `.mrc`/`.map`/`.bild`
files you own. The settings contain a command that is run by your shell, so the server answers those requests only when
they come from its own page (per-run token plus Host/Origin check); another web page you have open cannot change them or
trigger a launch. (ChimeraX's built-in REST, `remotecontrol rest start`, has no access token, which is why it is not used.)

## Ask an AI assistant about your project (MCP, read-only)

`reliontree mcp /path/to/project` is a small [MCP](https://modelcontextprotocol.io) server over standard input/output
(standard library only, no extra install). It answers "which job produced this map?", "what changed between these two
refinements?" and "draft the methods" from the project's own files. Six tools: `list_jobs`, `job_info`, `lineage`, `why`,
`diff`, `methods`. It is read-only: it cannot run, start or change RELION jobs, it is fixed to the one project directory,
validates job ids and never returns absolute paths. For Claude Code:
`claude mcp add reliontree -- reliontree mcp /path/to/project`; for other clients use
`{"command": "reliontree", "args": ["mcp", "/path/to/project"]}`.

## Testing

**1. Automated tests** (fast, no RELION project needed):

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest tests/ -v
```

Builds a fake RELION project internally and checks `tree`/`table`/JSON/HTML
output and exit codes.

**2. Against a real RELION project:**

```bash
source .venv/bin/activate
pip install -e .                        # installs the `reliontree` command into this venv
cd /path/to/your/relion_project          # must contain default_pipeline.star
reliontree                               # zero-config: opens the live view at http://127.0.0.1:8710
reliontree tree . --format text          # ASCII tree
reliontree tree . --format json | head -30
reliontree table . --format csv | head -5
reliontree methods .
reliontree tree . --format html -o tree.html   # old single-file static export
```

**3. Docs preview** (the Zensical guide):

```bash
pip install zensical
zensical serve
```

Opens `http://localhost:8000` with the built guide.

## Optional companion: relion-origin

reliontree works alone. If [relion-origin](https://github.com/LUKASinScience/relion-origin) is installed too, `reliontree analyze`
runs its per-particle checks (orientation gaps on the viewing sphere, classes that mix more than chance) and the findings
appear as pills on the job cards. relion-origin is imported by that one command only; everything else here never touches it.

```bash
pip install "git+https://github.com/LUKASinScience/relion-origin"     # numpy, pandas, starfile; brings reliontree along
reliontree analyze /path/to/project                                    # writes <project>/.reliontree/annotations/relion-origin.json
```

## Notes from other tools (annotations)

Other tools can attach short notes to jobs, shown as coloured pills on the job
card, a ⚑ in the sidebar and a "Notes from tools" section in the job panel.
The contract is only a file, so reliontree stays dependency-free and any tool
can write it:

```
<project>/.reliontree/annotations/<tool>.json
{"Class3D/job004": [{"label": "views: 52% of sphere sparse", "level": "warn", "detail": "..."}]}
```

`level` is `good`, `warn`, `bad` or `info`. One file per tool, so writers never
overwrite each other; malformed entries are ignored and text is length-capped.
Any script can write such a file. Two companion tools of the same author do (relion-origin: per-particle QC and
orientation gaps; relion-copilot: next-step proposals); relion-origin is [on GitHub](https://github.com/LUKASinScience/relion-origin), relion-copilot is not public. reliontree does not need either:
it has no dependencies, never imports them, and shows what it finds on its own (project type, orientation globe)
without them.

## How reliontree fits alongside other RELION tools

Follow_Relion_gracefully and CNIO_Relion_Tools are Streamlit/Dash apps —
a good fit when running a small web server and reaching it from a browser
is easy. himena-relion is a desktop GUI, which makes sense when you want a
full interactive workstation tool with a display attached. reliontree
targets a narrower situation those aren't aimed at: an SSH-only cluster
login node with no display and often no spare port to open. Its default
view is still live in a browser, just via Python's own stdlib
`http.server` bound to `127.0.0.1` — nothing to install, no port beyond
your own machine. When even that's not reachable, `reliontree tree
--format html -o tree.html` falls back to a single static file instead: `scp`
it back or open it over a mounted path.

Want to run `reliontree watch` as its own SLURM job instead of inside a GPU
allocation (it never needs a GPU, and shouldn't tie one up)?
[`contrib/slurm/`](contrib/slurm/) has a minimal, CPU-only `sbatch` template
and the SSH-tunnel steps to reach it from your laptop.

Cluster provides software via `module load` instead of `pip install`?
[`contrib/modules/`](contrib/modules/) has an Lmod/Tcl modulefile — once an
admin sets it up, `module load reliontree` puts the exact same `reliontree`
command (all the same subcommands and options) on `PATH`.

## Using reliontree as a library

Everything the CLI does is also a plain importable function — useful for a
notebook, a script, or another tool's pipeline:

```python
import reliontree

project = reliontree.find_project(".")        # or a specific path
tree = reliontree.build_tree(project)
html = reliontree.render_html(tree, title=str(project))

rows = reliontree.history_rows(
    reliontree.ordered_jobs(tree), tree["artifacts"], tree["parents"], tree["stats"],
)
csv_text = reliontree.rows_to_csv(rows)

# compare two jobs' options, or ask why a job exists relative to its parent
diff = reliontree.diff_options(tree["options"]["Refine3D/job039"], tree["options"]["Refine3D/job042"])
context = reliontree.job_context(tree, "Refine3D/job042")
```

`tree` is a plain dict — no custom classes to learn. The core keys are `layers`, `parents`, `artifacts`, `stats`, `options`
and `job_dirs`; around them: `alias`, `notes`, `classes`, `selection`, `latest`/`best`/`main`/`side` (the path to the latest
result), `masks`/`chips`, `annotations` and `experiment` (`{"type": "sta" | "spa" | "unknown", "evidence": ...}`).

## Origin

The pipeline-parsing and job-tree-diagram logic here started as the
Qt/ChimeraX-free core of the
[ChimeraX-InstantMap](https://github.com/LUKASinScience/ChimeraX-InstantMap)
plugin's RELION History tab — extracted into its own package since it
never needed ChimeraX to begin with. Homepage:
[github.com/LUKASinScience/ChimeraX-InstantMap](https://github.com/LUKASinScience/ChimeraX-InstantMap).

## Authors

- Lukas W. Bauer ([LUKASinScience](https://github.com/LUKASinScience)) — author
- Serhat Dönmez ([serhatdonmez98-cmd](https://github.com/serhatdonmez98-cmd)) — co-author;
  concept, screenshots and demo GIF for the README/docs
- Claude Code (Anthropic) — AI pair-programming assistant, wrote and
  reviewed a substantial part of this codebase alongside Lukas

## License

GNU Affero General Public License v3.0 (AGPL-3.0-or-later) — see
[LICENSE](LICENSE). ChimeraX-InstantMap itself stays MIT; both are the same
author's own code, so relicensing the part extracted here doesn't need
anyone else's sign-off. The practical effect of AGPL over plain GPL only
bites if someone runs `reliontree watch` as a shared network service for
other people — then those users must be offered the source, same as any
local modifications.

No third-party code is bundled or needed at run time (`dependencies = []`); the parts extracted from the author's own
ChimeraX-InstantMap plugin (MIT) are the same author's code. Formats and commands of RELION itself (GPL) are only read and
called, never copied.
