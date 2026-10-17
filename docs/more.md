# Library and other tools

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

## How reliontree fits alongside other RELION tools

[Follow_Relion_gracefully](https://github.com/dzyla/Follow_Relion_gracefully)
and [CNIO_Relion_Tools](https://github.com/cryoEM-CNIO/CNIO_Relion_Tools)
are Streamlit/Dash apps — a good fit when running a small web server and
reaching it from a browser is easy.
[himena-relion](https://github.com/hanjinliu/himena-relion) is a desktop
GUI, which makes sense when you want a full interactive workstation tool
with a display attached. reliontree targets a narrower situation those
aren't aimed at: an SSH-only cluster login node with no display and often
no spare port to open. Its default view is still live in a browser, just
via Python's own stdlib `http.server` bound to `127.0.0.1` — nothing to
install, no port beyond your own machine. When even that's not reachable,
`reliontree tree --format html -o tree.html` falls back to a single static
file instead.

Want to run `reliontree watch` as its own SLURM job instead of inside a GPU
allocation (it never needs a GPU, and shouldn't tie one up)? `contrib/slurm/`
in the repo has a minimal, CPU-only `sbatch` template and the SSH-tunnel
steps to reach it from your laptop.

Cluster provides software via `module load` instead of `pip install`?
`contrib/modules/` has an Lmod/Tcl modulefile — once an admin sets it up,
`module load reliontree` puts the exact same `reliontree` command (all the
same subcommands and options) on `PATH`.

