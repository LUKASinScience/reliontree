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

    state = "unknown"
    for marker, marker_state in STATE_MARKERS:
        if marker in names:
            state = marker_state
            break
    else:
        if any(n.lower() in ("run.out", "run.err") for n in names):
            state = "running"

    artifacts = {
        "state": state,
        "postprocess_map": None,
        "latest_map": None,
        "half_map_1": None,
        "half_map_2": None,
        "mask": None,
    }
    for name in names:
        lowered = name.lower()
        full = job_dir / name
        if lowered == "postprocess.mrc":
            artifacts["postprocess_map"] = full
        elif re.fullmatch(r"run_half1_class\d+_unfil\.mrc", lowered):
            artifacts["half_map_1"] = full
        elif re.fullmatch(r"run_half2_class\d+_unfil\.mrc", lowered):
            artifacts["half_map_2"] = full
        elif re.fullmatch(r"run_(it\d+_)?class\d+\.mrc", lowered) and artifacts["latest_map"] is None:
            artifacts["latest_map"] = full
        elif lowered.endswith(".mrc") and "mask" in lowered and artifacts["mask"] is None:
            artifacts["mask"] = full
    return artifacts


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

    return [by_class[c][1] for c in sorted(by_class)]


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
    m = re.search(r"^\s*" + re.escape(field_name) + r"\s+([\-0-9.eE]+)", text, re.MULTILINE)
    return float(m.group(1)) if m else None


def _sum_loop_column(text, field_name):
    """Sum a numeric column across every row of the `loop_` table that
    declares it — used for RELION's per-group `_rlnGroupNrParticles` to get
    a job's total particle count. Returns None if the column isn't found."""
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip().lower() == "loop_":
            i += 1
            cols = []
            while i < n and lines[i].lstrip().startswith("_"):
                cols.append(lines[i].split()[0])
                i += 1
            if field_name in cols:
                idx = cols.index(field_name)
                total = 0.0
                while i < n and lines[i].strip() \
                        and not lines[i].lstrip().startswith("_") \
                        and not lines[i].strip().lower().startswith("data_") \
                        and lines[i].strip().lower() != "loop_":
                    parts = lines[i].split()
                    if len(parts) > idx:
                        try:
                            total += float(parts[idx])
                        except ValueError:
                            pass
                    i += 1
                return int(total)
            continue
        i += 1
    return None


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


def job_stats(job_dir):
    """Best-effort {'resolution_angstrom': float|None, 'n_particles':
    int|None} for a job, read from files RELION itself writes: a
    PostProcess job's `postprocess.star` (`_rlnFinalResolution`, the gold-
    standard masked-FSC value, preferred when present) and a Class3D/
    Refine3D job's own `*_model.star` (`_rlnCurrentResolution` as a
    fallback, plus `_rlnGroupNrParticles` summed for the particle count).
    Pure — no Qt/ChimeraX dependency."""
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

    return {"resolution_angstrom": resolution, "n_particles": n_particles}


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
