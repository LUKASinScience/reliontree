# CryoSPARC -> RELION (checked)

`cs2relion.py` wraps pyem's `csparc2star.py` (GPL-3.0, run as an external program, nothing copied) and **validates the
result before RELION sees it**: optics table, pixel size, `N@stack.mrcs` image names, stacks on disk, optics group ids.
`fix-ext` makes the `.mrc` -> `.mrcs` rename safely (symlink + only the image-name column; a global `sed` also turns
`.mrcs` into `.mrcss` and edits micrograph names).

```bash
python3 cs2relion.py convert --particles J5_particles.cs --passthrough J5_passthrough_particles.cs --out particles.star --project .
python3 cs2relion.py validate particles.star --project /path/to/relion_project --json
python3 cs2relion.py fix-ext particles.star --project /path/to/relion_project
```

Needs `csparc2star.py` (`pip install` / clone of pyem; pass `--csparc2star` or set `CSPARC2STAR`). `--inverty` is on by default
because the two programs disagree on the y axis; `--no-inverty` turns it off.

**Tested with synthetic STAR files and a fake converter, not with a real CryoSPARC export.** Not checked: that Euler angles
mean the same in both programs (reconstruct and look), CTF values, half-set assignment.
