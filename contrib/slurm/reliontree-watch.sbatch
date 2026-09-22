#!/bin/bash
# Run `reliontree watch` as its own minimal SLURM job, instead of inside an
# interactive GPU allocation where it doesn't belong. reliontree does
# essentially no CPU work (it parses small .star files and serves a tiny
# SVG on request) so requesting a full node or a GPU for it would just take
# that resource away from someone who actually needs it. This script asks
# for exactly one CPU core and no GPU.
#
# Edit the two placeholders below for your cluster (account and partition
# names are site-specific — ask your HPC admins or check `sacctmgr`/`sinfo`
# if you don't know them), then submit with:
#
#   sbatch reliontree-watch.sbatch /path/to/your/relion_project
#
# Cancel it when you're done: `scancel <jobid>` (see `squeue --me`).

#SBATCH --job-name=reliontree
#SBATCH --account=<your-account>        # <-- edit: your SLURM account/allocation
#SBATCH --partition=<cpu-partition>     # <-- edit: a CPU-only partition, NOT the GPU one
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=512M
#SBATCH --time=04:00:00
#SBATCH --output=reliontree-%j.log
# No --gres=gpu line on purpose: this job must never land on a GPU node.

set -euo pipefail

PROJECT_DIR="${1:?Usage: sbatch reliontree-watch.sbatch /path/to/relion_project}"
PORT="${RELIONTREE_PORT:-8710}"
NODE="$(hostname)"

echo "reliontree watch starting on $NODE:$PORT for $PROJECT_DIR"
echo
echo "From your laptop, open an SSH tunnel:"
echo "  ssh -N -L ${PORT}:${NODE}:${PORT} $(whoami)@<your-cluster-login-host>"
echo "Then open http://127.0.0.1:${PORT}/ in your browser."
echo

# Adjust this if your site uses `module load python/...` instead of a
# pre-installed reliontree; reliontree has zero third-party dependencies,
# so a bare `python3 -m reliontree.cli` works once the package is on
# PYTHONPATH or pip-installed in whatever environment you activate here.
exec reliontree watch "$PROJECT_DIR" --port "$PORT" --no-open
