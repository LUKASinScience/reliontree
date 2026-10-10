"""Class2D/Class3D insight from files RELION already writes: per-iteration
class shares (`run_itNNN_model.star`), convergence (`_rlnChangesOptimalClasses`
in `run_itNNN_optimiser.star` -- the fraction of particles that switched
class that iteration), and the particle overlap between two classification
jobs (`class_overlap`, reads the big `*_data.star`, so only on demand).
Pure stdlib."""

import re
import struct

try:
    from .relion_artifacts import _find_scalar_field, _loop_column_values
except ImportError:
    from relion_artifacts import _find_scalar_field, _loop_column_values

# Single source of truth for the thresholds: the viewer (cards, drawer, JS)
# and relion-copilot's rule all read these.
SETTLED_CHANGES = 0.05    # <= this share of particles switching class per iteration = converged
TINY_SHARE = 0.02         # a class below this share of the particles counts as (nearly) empty

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


def class_selection(job_dir, n_classes):
    """Per-class keep flags of a "Select classes" job, positional in the
    order of the input classification's classes (`backup_selection.star`,
    RELION records no filenames there). None unless the file exists and its
    length matches `n_classes` -- a particle-subset Select has no such file
    or a mismatched one."""
    try:
        from .relion_artifacts import _parse_backup_selection_flags
    except ImportError:
        from relion_artifacts import _parse_backup_selection_flags
    try:
        flags = _parse_backup_selection_flags((job_dir / "backup_selection.star").read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return None
    return flags if len(flags) == n_classes else None


def _mrc_nz(path):
    try:
        with open(path, "rb") as f:
            return struct.unpack("<3i", f.read(12))[2]
    except (OSError, struct.error):
        return 0


def class_iter_thumbs(job_dir, iteration, size=72, only=None):
    """[data-URI, ...] one class-average thumbnail per class at the given
    iteration (3D: run_itNNN_classMMM.mrc volumes' middle slice; 2D: the
    slices of run_itNNN_classes.mrcs). [] if that iteration has no maps.
    `only`: set of 1-based class numbers to decode; the others stay in the
    list as None (index = class number - 1), so a 200-class Class2D job does
    not decode 200 images nobody will look at."""
    try:
        from .relion_mrc_thumb import mrc_slice_thumbnail
    except ImportError:
        from relion_mrc_thumb import mrc_slice_thumbnail
    wanted = lambda n: only is None or n in only
    stack = job_dir / ("run_it%03d_classes.mrcs" % iteration)
    if stack.is_file():
        if only is not None:
            return [mrc_slice_thumbnail(stack, size=size, z=z) if wanted(z + 1) else None for z in range(_mrc_nz(stack))]
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
        out.append(mrc_slice_thumbnail(path, size=size) if wanted(n) else None)
    return out


def class_convergence(hist):
    """What a classification's history (`class_history`) shows -- a statement, not a recommendation -- or None if there
    are fewer than 3 iterations to judge: {"converged": bool, "switching": share of particles that changed class in the
    last iteration, "iter": that iteration, "empty_classes": [numbers of classes below TINY_SHARE], "n_classes": int,
    "message": str}. "converged" = at most SETTLED_CHANGES switching. What to do about it (more iterations, more or
    fewer classes) is relion-copilot's job, not this viewer's."""
    pts = [h for h in hist if h["changes_classes"] is not None and h["iter"] > 0]
    if len(pts) < 3:
        return None
    last, shares = pts[-1], hist[-1]["shares"]
    switching = last["changes_classes"]
    converged = switching <= SETTLED_CHANGES
    empty = [i + 1 for i, v in enumerate(shares) if v < TINY_SHARE]
    message = ("Converged: %.1f%% of particles switched class in iteration %d." if converged else
               "Not converged: %.1f%% of particles still switched class in iteration %d.") % (switching * 100, last["iter"])
    if empty and not converged:
        message += " Nearly empty: class %s." % ", ".join(map(str, empty))
    return {"converged": converged, "switching": switching, "iter": last["iter"], "empty_classes": empty,
            "n_classes": len(shares), "message": message}


def match_columns(classes_a, classes_b, counts):
    """Greedy best-match column order for an overlap matrix: repeatedly
    pair the largest remaining (a, b) cell, so a permuted-but-identical
    classification shows up on the diagonal. Returns (order_b, score) where
    score = matched particles / all particles."""
    total = sum(counts.values()) or 1
    used_a, used_b, matched, pairs = set(), set(), 0, {}
    for (a, b), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if a not in used_a and b not in used_b:
            used_a.add(a); used_b.add(b); matched += n; pairs[a] = b
    order = [pairs[a] for a in classes_a if a in pairs] + [b for b in classes_b if b not in used_b]
    return order, matched / total


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
    ca_, cb_ = sorted({a for a, _ in counts}), sorted({b for _, b in counts})
    order_b, score = match_columns(ca_, cb_, counts)
    return {"classes_a": ca_, "classes_b": cb_, "counts": counts, "order_b": order_b, "score": score}
