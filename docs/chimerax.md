# ChimeraX and 3D

Every job card that holds a map has a blue **3D** chip (and a violet **Mask** chip). The Details drawer lists everything
a job holds: post-processed map, final map, all classes, half maps, masks and angular-distribution `.bild` files.

## What you need

- **ChimeraX** (any recent version) on the machine that shows the maps. On a cluster this is usually `module load chimerax`
  (see *Settings* below).
- **InstantMap is optional.** reliontree starts ChimeraX with its own listener, so the 3D buttons work in a plain ChimeraX.
  [ChimeraX-InstantMap](https://github.com/LUKASinScience/ChimeraX-InstantMap) adds `instantmap listen` for a window you
  already have open, and masks and RELION tools of its own.

## One window, no open port

A click hands the map to **one** ChimeraX window. reliontree never opens a network port towards ChimeraX (ChimeraX's own
REST interface has no token, so any web page could drive it). Instead it writes a small request file into a private
directory (`~/.reliontree/chimerax`, mode 0700); a listener inside ChimeraX picks it up and runs only `open <map>`
(plus `tile` and an optional FigureStyle template). Requests must come from your own user, be younger than five minutes
and name existing `.mrc`/`.map`/`.bild` files.

If no ChimeraX with the listener runs, the first click starts one with reliontree's own listener; every later click
goes to that window. You do not need InstantMap for this. For a ChimeraX you already have open:

```
runscript /path/printed/by/reliontree-listener-path
```

(or `instantmap listen` with ChimeraX-InstantMap).

## Settings (clusters and modules)

The gear icon opens the settings; the same from the shell:

```bash
reliontree settings                                   # show
reliontree settings --chimerax /opt/chimerax/bin/chimerax
reliontree settings --run-first "module load chimerax"
reliontree settings --check                           # runs the snippet and `ChimeraX --version`
```

*Run first* is a shell snippet executed before ChimeraX is started (typically `module load ...`). Both fields are run by
the shell on the machine where reliontree runs, which is why the web page can only change them with a per-run token and
from its own origin. On a cluster ChimeraX needs a display (for example `ssh -X`).

## From the shell

```bash
reliontree maps --job Refine3D/job042                     # what is there
reliontree open --job Refine3D/job042                     # most important map
reliontree open --job Refine3D/job042 --map mask          # pick by label
reliontree open --job Class3D/job010 --no-tile            # several maps, not side by side
```

## Figure styles

With the [FigureStyle](https://github.com/LUKASinScience/ChimeraX-FigureStyle) bundle installed, reliontree can apply a
style template to what it opens: set *FigureStyle template* in the settings (or `--template` on `open`). The first map of
a click becomes the template's map, the second its second map (mask, half map), for example *Mask overlay* or
*Half-map comparison*. Without FigureStyle, or with a misspelt name, the maps still open and ChimeraX logs a warning.
Thresholds in the templates are starting points: set the level per map and state it in the figure legend.
