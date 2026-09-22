# Running reliontree as its own SLURM job

Not part of the `reliontree` package — a standalone, optional script for
people who'd rather submit reliontree as its own minimal SLURM job than run
it inside an interactive GPU allocation where it doesn't belong.
reliontree does essentially no CPU work (it parses small `.star` files and
serves a tiny generated SVG per request), so it never needs a GPU and never
needs more than one core.

## Usage

1. Edit `reliontree-watch.sbatch`: fill in your SLURM `--account` and a
   **CPU-only** `--partition` (ask your HPC admins or check `sinfo` if you
   don't know the partition names on your cluster — every site names these
   differently, so this can't be filled in generically).
2. Submit it:
   ```bash
   sbatch reliontree-watch.sbatch /path/to/your/relion_project
   ```
3. Check the job's log (`reliontree-<jobid>.log`) for the compute node
   hostname and the exact `ssh -L ...` tunnel command to run from your
   laptop, then open `http://127.0.0.1:8710/` in your browser.
4. When you're done: `scancel <jobid>` (find it with `squeue --me`).

## Why this exists instead of just running `reliontree watch` directly

If you already have an interactive job or allocation open (e.g. for RELION
itself) it's simplest to just run `reliontree watch` in a terminal inside
that session — no need for this script at all. This script is for the
separate case where you want reliontree running on its own, independent of
whatever GPU job you're also running, without accidentally scheduling it
onto (and holding open) a scarce GPU node for a tool that never touches the
GPU.
