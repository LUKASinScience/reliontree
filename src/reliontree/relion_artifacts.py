import re
import shlex

STATE_MARKERS = (
    ("RELION_JOB_EXIT_FAILURE", "failed"),
    ("RELION_JOB_EXIT_ABORTED", "aborted"),
    ("RELION_JOB_ABORT_NOW", "aborted"),
    ("RELION_JOB_EXIT_SUCCESS", "succeeded"),
)


def scan_job_artifacts(job_dir):
    """Classify a RELION job directory's output files. Filename conventions
    and state-sentinel files follow RELION's own output layout; unmatched
    files are simply ignored (best-effort)."""
    try:
        names = [f.name for f in job_dir.iterdir() if f.is_file()]
    except OSError:
        names = []

    state, from_marker = "unknown", False
    for marker, marker_state in STATE_MARKERS:
        if marker in names:
            state, from_marker = marker_state, True
            break
    else:
        # a guess: a job that wrote run.out/run.err and no exit marker. Deposited or copied projects often lack
        # the markers of finished jobs, so build_tree lets the pipeline's own status label override this guess.
        if any(n.lower() in ("run.out", "run.err") for n in names):
            state = "running"

    artifacts = {
        "state": state,
        "state_from_marker": from_marker,
        "postprocess_map": None,
        "latest_map": None,
        "half_map_1": None,
        "half_map_2": None,
        "mask": None,
    }
    latest_key = None
    for name in sorted(names):
        lowered = name.lower()
        full = job_dir / name
        if lowered == "postprocess.mrc":
            artifacts["postprocess_map"] = full
        elif re.fullmatch(r"run_half1_class\d+_unfil\.mrc", lowered):
            artifacts["half_map_1"] = full
        elif re.fullmatch(r"run_half2_class\d+_unfil\.mrc", lowered):
            artifacts["half_map_2"] = full
        elif re.fullmatch(r"run_(it\d+_)?class\d+\.mrc", lowered):
            m = re.fullmatch(r"run_(?:it(\d+)_)?class(\d+)\.mrc", lowered)
            # highest iteration wins (numeric); a final run_classNNN without it counts as above any iteration
            key = (int(m.group(1)) if m.group(1) else 10 ** 9, -int(m.group(2)))
            if latest_key is None or key > latest_key:
                latest_key, artifacts["latest_map"] = key, full
        elif lowered.endswith(".mrc") and "mask" in lowered and artifacts["mask"] is None:
            artifacts["mask"] = full
    return artifacts


def nr_classes(job_dir):
    """Number of classes the job's newest `run_*model.star` declares (`_rlnNrClasses`), or None. Leftover class maps of an
    earlier run with more classes can sit in the same directory; this is what tells them apart."""
    try:
        models = sorted(job_dir.glob("run_it*_model.star")) or [job_dir / "run_model.star"]
        with open(models[-1], encoding="utf-8", errors="ignore") as fh:
            m = re.search(r"^_rlnNrClasses\s+(\d+)", fh.read(20000), re.M)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def list_class_maps(job_dir):
    """All per-class 3D volumes in a job directory (Class3D-style jobs),
    one per class number, keeping only the highest RELION iteration present
    for that class (so a job with many iterations doesn't yield one map per
    iteration per class — just the final one per class). Sorted by class
    number. Pure — no Qt/ChimeraX dependency."""
    try:
        names = [f.name for f in job_dir.iterdir() if f.is_file()]
    except OSError:
        return []

    pattern = re.compile(r"run_(?:it(\d+)_)?class(\d+)\.mrc", re.IGNORECASE)
    by_class = {}
    for name in names:
        m = pattern.fullmatch(name)
        if not m:
            continue
        iteration = int(m.group(1)) if m.group(1) else -1
        class_num = int(m.group(2))
        if class_num not in by_class or iteration > by_class[class_num][0]:
            by_class[class_num] = (iteration, job_dir / name)

    limit = nr_classes(job_dir) if by_class else None
    return [by_class[c][1] for c in sorted(by_class) if limit is None or c <= limit]


def list_class_stack(job_dir):
    """A Class2D job's latest per-iteration class-average stack
    (`run_itNNN_classes.mrcs`, one Z-slice per class), or None."""
    best, best_it = None, -1
    try:
        names = [f.name for f in job_dir.iterdir() if f.is_file()]
    except OSError:
        return None
    for name in names:
        m = re.fullmatch(r"run_it(\d+)_classes\.mrcs", name)
        if m and int(m.group(1)) > best_it:
            best_it, best = int(m.group(1)), job_dir / name
    return best


_MAX_SCAN_BYTES = 2_000_000  # option/selection files are tiny; skip large
                              # per-particle data tables (e.g. particles.star)


def _parse_backup_selection_flags(text):
    """Parse a RELION "Select classes" job's `backup_selection.star`: a bare
    list of `_rlnSelected` 0/1 flags, in the same order as the classes of
    the input model it ran on — RELION's interactive class-selection GUI
    doesn't record filenames here at all, only positional keep/discard
    flags. Returns a list of booleans in that order."""
    flags = []
    in_loop = False
    saw_col = False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.lower() == "loop_":
            in_loop, saw_col = True, False
            continue
        if s.lower().startswith("data_"):
            in_loop = False
            continue
        if in_loop and s.startswith("_"):
            if s.split()[0] == "_rlnSelected":
                saw_col = True
            continue
        if in_loop and saw_col:
            try:
                flags.append(int(s.split()[0]) != 0)
            except ValueError:
                pass
    return flags


def referenced_class_maps(job_dir, candidate_paths):
    """Which of `candidate_paths` (e.g. an upstream Class3D job's per-class
    volumes, already sorted by class number) this job actually references
    as input. Two RELION mechanisms are checked:

    - A job that names one specific class directly as its own reference
      (e.g. a Refine3D job's `job.star` "reference map" parameter) — found
      via a best-effort text search across the job's own small `*.star`
      files (plus `note.txt`; large per-particle tables like
      `particles.star` are skipped, both by name and by a size cutoff).
    - A "Select classes" (Subset selection) job — these don't name
      filenames at all; they write `backup_selection.star`, a bare list of
      positional `_rlnSelected` 0/1 flags in the same order as the input
      model's classes, matched up here against `candidate_paths` by
      position (both are in ascending class-number order).

    RELION doesn't record per-class selection in `default_pipeline.star`
    itself (edges there are per-job, not per-file-within-a-job), so this is
    necessarily best-effort rather than a pipeline-graph lookup. Pure — no
    Qt/ChimeraX dependency."""
    # backup_selection.star, when present and matching in length, is
    # authoritative for a Select job — it's checked on its own (not unioned
    # with the filename scan below) because a Select job's own
    # job_pipeline.star is a full snapshot of the *entire* pipeline graph at
    # that point, so it lists every upstream class filename as a node
    # regardless of which ones were actually kept; unioning it in would
    # mark every class as "selected".
    backup = job_dir / "backup_selection.star"
    if backup.is_file():
        try:
            flags = _parse_backup_selection_flags(backup.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            flags = []
        if len(flags) == len(candidate_paths):
            return {str(p) for p, selected in zip(candidate_paths, flags) if selected}

    # otherwise, a best-effort text search across the job's own small
    # option files for one specific class named directly (e.g. a Refine3D
    # job's "reference map" parameter) — pipeline-snapshot files and large
    # per-particle tables are excluded, both by name and by a size cutoff
    _SKIP_NAMES = {"particles.star", "job_pipeline.star", "default_pipeline.star"}
    try:
        text_files = [
            f for f in job_dir.glob("*.star")
            if f.name not in _SKIP_NAMES and f.stat().st_size <= _MAX_SCAN_BYTES
        ]
    except OSError:
        text_files = []
    note = job_dir / "note.txt"
    try:
        if note.is_file() and note.stat().st_size <= _MAX_SCAN_BYTES:
            text_files.append(note)
    except OSError:
        pass

    combined = []
    for f in text_files:
        try:
            combined.append(f.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    text = "\n".join(combined)
    return {str(p) for p in candidate_paths if p.name in text}


def _find_scalar_field(text, field_name):
    """Find a flat (non-loop) STAR field's value, e.g. a `data_model_general`
    block's `_rlnCurrentResolution   22.996479` line. Field names are
    unique enough within a RELION model/postprocess star file that a direct
    regex search is reliable without a full STAR parser."""
    m = re.search(r"^\s*" + re.escape(field_name) + r"\s+([\-+0-9.eE]+)", text, re.MULTILINE)
    return float(m.group(1)) if m else None


def _loop_column_values(text, field_name):
    """Every numeric value of a `loop_` column across the STAR file (e.g.
    all `_rlnDefocusU` values, one per micrograph/particle). Returns []
    if the column isn't found."""
    lines = text.splitlines()
    i, n = 0, len(lines)
    out = []
    while i < n:
        if lines[i].strip().lower() == "loop_":
            i += 1
            cols = []
            while i < n and lines[i].lstrip().startswith("_"):
                cols.append(lines[i].split()[0])
                i += 1
            if field_name in cols:
                idx = cols.index(field_name)
                while i < n and lines[i].strip() \
                        and not lines[i].lstrip().startswith("_") \
                        and not lines[i].strip().lower().startswith("data_") \
                        and lines[i].strip().lower() != "loop_":
                    parts = lines[i].split()
                    if len(parts) > idx:
                        try:
                            out.append(float(parts[idx]))
                        except ValueError:
                            pass
                    i += 1
                return out
            continue
        i += 1
    return out


def _sum_loop_column(text, field_name):
    """Sum a numeric column across every row of the `loop_` table that
    declares it — used for RELION's per-group `_rlnGroupNrParticles` to get
    a job's total particle count. Returns None if the column isn't found."""
    values = _loop_column_values(text, field_name)
    return int(sum(values)) if values else None


def _latest_model_star(job_dir):
    """RELION writes a per-iteration `run_it0NN_model.star` for a running
    Class3D/Refine3D job, and a final `run_model.star` once it's done."""
    final = job_dir / "run_model.star"
    if final.is_file():
        return final
    pattern = re.compile(r"run_it(\d+)_model\.star$")
    best, best_it = None, -1
    try:
        names = [f.name for f in job_dir.iterdir() if f.is_file()]
    except OSError:
        return None
    for name in names:
        m = pattern.fullmatch(name)
        if m:
            it = int(m.group(1))
            if it > best_it:
                best_it, best = it, job_dir / name
    return best


def _refine_particle_total(job_dir):
    """Particle count of a gold-standard Refine3D job, both halves together. RELION splits the data into two random halves and writes
    one `*_half1_model.star` and one `*_half2_model.star` per iteration, each counting only its own half, and
    `run_model.star` does the same -- a single model.star shows one half (the number the cards show, as in half-map work). Sums both halves of the
    newest iteration that has both; None when this isn't a half-split job."""
    pattern = re.compile(r"run_it(\d+)_half([12])_model\.star$")
    found = {}
    try:
        for f in job_dir.iterdir():
            m = pattern.fullmatch(f.name)
            if m:
                found.setdefault(int(m.group(1)), {})[m.group(2)] = f
    except OSError:
        return None
    for it in sorted(found, reverse=True):
        if len(found[it]) == 2:
            try:
                counts = [_sum_loop_column(f.read_text(encoding="utf-8", errors="ignore"), "_rlnGroupNrParticles")
                          for f in found[it].values()]
            except OSError:
                return None
            return sum(counts) if all(c is not None for c in counts) else None
    return None


def _runtime_seconds(job_dir):
    """Best-effort wall-clock runtime: mtime of job.star (job was set up)
    to mtime of whichever RELION_JOB_EXIT_* sentinel is present (job
    finished/failed/aborted) — both are files RELION itself writes, no
    dependency on a scheduler's own accounting. None if the job hasn't
    finished yet, or job.star is missing."""
    job_star = job_dir / "job.star"
    if not job_star.is_file():
        return None
    try:
        start = job_star.stat().st_mtime
    except OSError:
        return None
    for marker, _ in STATE_MARKERS:
        marker_path = job_dir / marker
        if marker_path.is_file():
            try:
                end = marker_path.stat().st_mtime
            except OSError:
                return None
            return max(0.0, end - start)
    return None


def job_stats(job_dir):
    """Best-effort {'resolution_angstrom': float|None, 'n_particles':
    int|None, 'runtime_seconds': float|None} for a job, read from files
    RELION itself writes: a PostProcess job's `postprocess.star`
    (`_rlnFinalResolution`, the gold-standard masked-FSC value, preferred
    when present) and a Class3D/Refine3D job's own `*_model.star`
    (`_rlnCurrentResolution` as a fallback, plus `_rlnGroupNrParticles`
    summed for the particle count); runtime from job.star's mtime to the
    RELION_JOB_EXIT_* sentinel's mtime. Pure — no Qt/ChimeraX dependency."""
    resolution = None
    n_particles = None

    postprocess_star = job_dir / "postprocess.star"
    if postprocess_star.is_file():
        try:
            resolution = _find_scalar_field(
                postprocess_star.read_text(encoding="utf-8", errors="ignore"), "_rlnFinalResolution")
        except OSError:
            pass

    model_star = _latest_model_star(job_dir)
    if model_star is not None:
        try:
            text = model_star.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = None
        if text is not None:
            if resolution is None:
                resolution = _find_scalar_field(text, "_rlnCurrentResolution")
            n_particles = _sum_loop_column(text, "_rlnGroupNrParticles")
    n_total = _refine_particle_total(job_dir)   # both random halves; n_particles stays what run_model.star reports (one half)

    return {
        "resolution_angstrom": resolution,
        "n_particles": n_particles,
        "n_particles_total": n_total if n_total is not None else n_particles,
        "runtime_seconds": _runtime_seconds(job_dir),
    }


def parse_job_options(job_dir):
    """Parse a job's own `job.star` `_rlnJobOptionVariable`/
    `_rlnJobOptionValue` loop into a plain {variable: value} dict of
    strings (RELION's own record of exactly what parameters a job was run
    with) — used to draft a methods-section paragraph. Pure."""
    job_star = job_dir / "job.star"
    try:
        text = job_star.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    lines = text.splitlines()
    i, n = 0, len(lines)
    options = {}
    while i < n:
        if lines[i].strip().lower() == "loop_":
            i += 1
            cols = []
            while i < n and lines[i].lstrip().startswith("_"):
                cols.append(lines[i].split()[0])
                i += 1
            if "_rlnJobOptionVariable" in cols and "_rlnJobOptionValue" in cols:
                var_idx = cols.index("_rlnJobOptionVariable")
                val_idx = cols.index("_rlnJobOptionValue")
                while i < n and lines[i].strip() \
                        and not lines[i].lstrip().startswith("_") \
                        and not lines[i].strip().lower().startswith("data_") \
                        and lines[i].strip().lower() != "loop_":
                    try:
                        parts = shlex.split(lines[i].strip())
                    except ValueError:
                        parts = lines[i].split()
                    if len(parts) > max(var_idx, val_idx):
                        options[parts[var_idx]] = parts[val_idx]
                    i += 1
            continue
        i += 1
    return options


def artifact_badge(artifacts):
    tags = ["[%s]" % artifacts["state"]]
    if artifacts["postprocess_map"]:
        tags.append("[postprocess]")
    elif artifacts["latest_map"]:
        tags.append("[map]")
    if artifacts["half_map_1"] and artifacts["half_map_2"]:
        tags.append("[half-maps]")
    if artifacts["mask"]:
        tags.append("[mask]")
    return " ".join(tags)
