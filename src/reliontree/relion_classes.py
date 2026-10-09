"""Class2D/Class3D insight from files RELION already writes: per-iteration
class shares (`run_itNNN_model.star`), convergence (`_rlnChangesOptimalClasses`
in `run_itNNN_optimiser.star` -- the fraction of particles that switched
class that iteration), and the particle overlap between two classification
jobs (`class_overlap`, reads the big `*_data.star`, so only on demand).
Pure stdlib."""

import re

try:
    from .relion_artifacts import _find_scalar_field, _loop_column_values
except ImportError:
    from relion_artifacts import _find_scalar_field, _loop_column_values

_ITER = re.compile(r"run_it(\d+)_model\.star$")


def class_history(job_dir):
    """[{iter, shares: [..], changes_classes: float|None}] oldest first, one
    entry per iteration that has a model.star. [] if the job has none."""
    out = []
    for model in sorted(job_dir.glob("run_it*_model.star")):
        m = _ITER.fullmatch(model.name)
        if not m:
            continue
        try:
            text = model.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        shares = _loop_column_values(text, "_rlnClassDistribution")
        if not shares:
            continue
        changes = None
        opt = model.with_name(model.name.replace("_model.", "_optimiser."))
        try:
            changes = _find_scalar_field(opt.read_text(encoding="utf-8", errors="ignore"), "_rlnChangesOptimalClasses")
        except OSError:
            pass
        out.append({"iter": int(m.group(1)), "shares": shares, "changes_classes": changes})
    return out


def class_iter_thumbs(job_dir, iteration, size=72):
    """[data-URI, ...] one class-average thumbnail per class at the given
    iteration (3D: run_itNNN_classMMM.mrc volumes' middle slice; 2D: the
    slices of run_itNNN_classes.mrcs). [] if that iteration has no maps."""
    try:
        from .relion_mrc_thumb import mrc_slice_thumbnail
    except ImportError:
        from relion_mrc_thumb import mrc_slice_thumbnail
    stack = job_dir / ("run_it%03d_classes.mrcs" % iteration)
    if stack.is_file():
        out, z = [], 0
        while True:
            uri = mrc_slice_thumbnail(stack, size=size, z=z)
            if uri is None:
                return out
            out.append(uri)
            z += 1
    out = []
    for n in range(1, 64):
        path = job_dir / ("run_it%03d_class%03d.mrc" % (iteration, n))
        if not path.is_file():
            break
        out.append(mrc_slice_thumbnail(path, size=size))
    return out


def _particle_classes(data_star):
    """{rlnImageName: rlnClassNumber} streamed from a data.star's particle loop."""
    classes = {}
    cols, idx = None, None
    in_loop = False
    with open(data_star, encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s.lower() == "loop_":
                in_loop, cols = True, []
            elif in_loop and s.startswith("_"):
                cols.append(s.split()[0])
            elif in_loop and s and not s.startswith(("#", "data_")):
                if idx is None:
                    if "_rlnImageName" not in cols or "_rlnClassNumber" not in cols:
                        in_loop, cols = False, None  # some other loop, keep looking
                        continue
                    idx = (cols.index("_rlnImageName"), cols.index("_rlnClassNumber"))
                parts = s.split()
                classes[parts[idx[0]]] = int(parts[idx[1]])
            elif in_loop and idx is not None and (not s or s.startswith("data_")):
                break
    return classes


def _final_data_star(job_dir):
    final = job_dir / "run_data.star"
    if final.is_file():
        return final
    its = sorted(job_dir.glob("run_it*_data.star"))
    return its[-1] if its else None


def class_overlap(job_dir_a, job_dir_b):
    """Particle-count matrix between two classification jobs:
    {"classes_a": [..], "classes_b": [..], "counts": {(a, b): n}}. Particles
    are matched on rlnImageName; ones in only one job are ignored.
    None if either job has no data.star."""
    sa, sb = _final_data_star(job_dir_a), _final_data_star(job_dir_b)
    if sa is None or sb is None:
        return None
    ca, cb = _particle_classes(sa), _particle_classes(sb)
    counts = {}
    for name, a in ca.items():
        b = cb.get(name)
        if b is not None:
            counts[(a, b)] = counts.get((a, b), 0) + 1
    return {"classes_a": sorted({a for a, _ in counts}), "classes_b": sorted({b for _, b in counts}),
            "counts": counts}
