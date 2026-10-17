# FAQ

**No 3D chip on a job.** The job folder holds no `.mrc`/`.map` file next to its own files, or it holds many unrelated
maps (a folder with more than 60 non-iteration maps is treated as a data dump). Per-iteration class maps of a long
classification do not count towards that limit. `reliontree maps --job X` shows what reliontree found.

**Every click opens a new ChimeraX window.** The listener is not running in the window you expect. Check
`reliontree settings`: it reports whether a listener is connected. Start one in an open window with `runscript` and the
path from `reliontree listener-path`.

**ChimeraX does not start from a cluster login node.** Set *Run first* (for example `module load chimerax`) and make sure
a display is available (`ssh -X`); `reliontree settings --check` runs the same lines without opening a window.

**The template was not applied.** FigureStyle (1.2 or newer) must be installed in that ChimeraX; the log shows a
warning otherwise. Template names may contain letters, digits, spaces, `_`, `.` and `-` only.

**Windows / macOS / Linux.** Developed and tested on macOS. Linux should work (same code paths, not tested here);
Windows is untested.
