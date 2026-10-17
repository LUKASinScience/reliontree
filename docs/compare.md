# Comparing jobs

Two questions come up constantly: *what is different between these runs?* and *which one is better?* reliontree
answers both in the browser and in the shell, from the same data.

## In the browser

Tick two or more jobs in the sidebar and press **Compare**: the changed options, and for two Class2D/Class3D jobs the
particle-overlap heatmap (which class of job A went to which class of job B).

## In the shell: `reliontree compare`

```bash
reliontree compare . --job Class3D/job010 --job Class3D/job015
reliontree compare . --job Refine3D/job039 --job Refine3D/job040 --job Refine3D/job041 --format json
```

One call gives:

| Part | Content |
|---|---|
| jobs | type, state, parent(s), resolution (Å), particle count and the maps each job holds |
| options | exactly two jobs: *changed* options (`a -> b`); three or more: options that *vary* across the jobs |
| overlap | two Class2D/Class3D jobs only: particles per class pair and the share on the diagonal |

`--format json` returns the same as one object (`jobs`, `options`, `overlap`) for scripts and AI assistants.
A job that is not in the pipeline gives exit code 2.

Smaller pieces, if you only need one:

```bash
reliontree diff --job A --job B        # options only
reliontree overlap Class3D/job010 Class3D/job015
reliontree why --job Refine3D/job042   # what changed against the parent
reliontree maps --job Refine3D/job042  # which maps a job holds
```

## Reading the result

- A changed option is a candidate explanation, not a proof: several options usually change together.
- The overlap score is the share of particles on the best-matching diagonal. It is high when two classifications agree
  and low when they carve the data differently. It says nothing about which one is right.
- Resolution values come from the job's own output (the final FSC); runs with different masks or particle sets are not
  directly comparable.

To look at the maps of the compared jobs side by side in ChimeraX, see [ChimeraX and 3D](chimerax.md).
