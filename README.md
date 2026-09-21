# reliontree

Standalone RELION job-lineage viewer. No ChimeraX, no third-party server
framework, no GUI toolkit — the default path is a self-starting stdlib-only
local server. Works on a workstation, an HPC login node (no X11, no root),
or a cloud VM, with the same single command.

```bash
uvx reliontree
```

Run from inside (or under) a RELION project directory. Zero arguments:
detects `default_pipeline.star` and opens a live local view in your
browser — job cards with map thumbnails, click-to-browse sidebar, and a
directory picker if no project is found yet. No project directory handy?
`reliontree` still starts and lets you browse to one. On a machine with no
browser (a login node), use `reliontree tree --format html -o tree.html`
for the old single-file static export instead.

No `uv`? `pipx run reliontree` works the same way. Want it installed
persistently in an existing env: `pip install reliontree`.

![reliontree — job tree view](docs/assets/screenshot-tree.png)
![reliontree — live browsing demo](docs/assets/demo.gif)

## Usage

```bash
reliontree                                    # zero-config: opens the live view
reliontree /path/to/project                   # same, pointed at an explicit directory
reliontree tree . --format text               # ASCII tree in the terminal
reliontree tree . --format json               # machine-readable, for scripts/agents
reliontree tree . --job Class3D/job012        # just that job's upstream lineage
reliontree table . --format csv -o jobs.csv   # job table for a supplement
reliontree methods .                          # draft methods-paragraph, one line per job
reliontree tree . --format html -o tree.html  # old single-file static export
```

Exit codes for the `tree`/`table`/`methods` subcommands (for scripting):
`0` ok, `1` no RELION project found, `2`
parse/job-lookup error.

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

## Origin

The pipeline-parsing and job-tree-diagram logic here started as the
Qt/ChimeraX-free core of the
[ChimeraX-InstantMap](https://github.com/LUKASinScience/ChimeraX-InstantMap)
plugin's RELION History tab — extracted into its own package since it
never needed ChimeraX to begin with. Homepage:
[github.com/LUKASinScience/ChimeraX-InstantMap](https://github.com/LUKASinScience/ChimeraX-InstantMap).

## Contributors

- Lukas W. Bauer ([LUKASinScience](https://github.com/LUKASinScience)) — author
- Claude Code (Anthropic) — AI pair-programming assistant, wrote and
  reviewed a substantial part of this codebase alongside Lukas
- Serhat Dönmez ([serhatdonmez98-cmd](https://github.com/serhatdonmez98-cmd)) —
  concept, screenshots and demo GIF for the README/docs

## License

GNU Affero General Public License v3.0 (AGPL-3.0-or-later) — see
[LICENSE](LICENSE). ChimeraX-InstantMap itself stays MIT; both are the same
author's own code, so relicensing the part extracted here doesn't need
anyone else's sign-off. The practical effect of AGPL over plain GPL only
bites if someone runs `reliontree watch` as a shared network service for
other people — then those users must be offered the source, same as any
local modifications.
