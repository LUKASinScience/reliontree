# `module load reliontree` on an HPC cluster

Not part of the `reliontree` package — an optional environment-modules
setup for clusters that provide software via `module load` (Lmod or
classic Environment Modules) instead of per-user `pip install`.

## One-time setup (an HPC admin does this)

1. Install reliontree into its own shared, versioned location:
   ```bash
   ./install.sh /shared/apps/reliontree/0.1.0
   ```
   (creates a venv there and installs reliontree into it — zero third-party
   dependencies, so nothing else ends up in that venv)
2. Edit `install_dir` in `reliontree/0.1.0.lua` (Lmod) and/or `reliontree/0.1.0`
   (classic Tcl modulefile) to that same path.
3. Copy the `reliontree/` directory into somewhere on `$MODULEPATH`, e.g.:
   ```bash
   cp -r reliontree /shared/modulefiles/
   ```

## What a user does after that

```bash
module load reliontree
reliontree                       # exact same command + all the same options as always
reliontree tree . --format json
reliontree watch . --port 8710
```

`module load` only ever does one thing here: prepends that shared venv's
`bin/` to `PATH`. Nothing about reliontree itself changes — every
subcommand, flag, and the zero-config live view work identically to a
regular `pip install`.

## Updating to a new reliontree version

Run `install.sh` again with a new version directory
(`/shared/apps/reliontree/0.2.0`), add a matching `0.2.0.lua`/`0.2.0` next
to the existing ones, and users can `module load reliontree/0.2.0`
specifically, or keep using the old version until you mark the new one
default (`module-version` in Lmod, or a `.version` file in classic
modules) — standard practice for any versioned module, nothing
reliontree-specific.
