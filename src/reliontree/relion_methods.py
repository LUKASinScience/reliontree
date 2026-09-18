"""Best-effort "Methods" paragraph draft assembled from a RELION job
lineage's own recorded parameters and stats — a starting point to edit,
not a citation-ready sentence. Pure — no Qt/ChimeraX dependency."""

_SYMMETRY_KEYS = ("sym_name", "sym")
_DIAMETER_KEYS = ("particle_diameter",)
_NR_CLASSES_KEYS = ("nr_classes",)


def _option(options, keys):
    for key in keys:
        value = options.get(key)
        if value not in (None, "", '""'):
            return value
    return None


def _format_number(n):
    try:
        return format(int(round(float(n))), ",")
    except (TypeError, ValueError):
        return str(n)


def job_sentence(job_id, options, stats):
    """One best-effort line describing a single job's parameters (from its
    own `job.star` options) and outcome (from `relion_artifacts.
    job_stats()`)."""
    options = options or {}
    stats = stats or {}

    details = []
    sym = _option(options, _SYMMETRY_KEYS)
    if sym and sym.upper() != "C1":
        details.append("%s symmetry" % sym)
    n_classes = _option(options, _NR_CLASSES_KEYS)
    if n_classes and n_classes != "1":
        details.append("%s classes" % n_classes)
    diameter = _option(options, _DIAMETER_KEYS)
    if diameter:
        details.append("%s Å particle diameter" % diameter)

    detail_str = " (%s)" % ", ".join(details) if details else ""
    line = "%s%s" % (job_id, detail_str)

    outcome = []
    resolution = stats.get("resolution_angstrom")
    if resolution:
        outcome.append("%.1f Å" % resolution)
    n_particles = stats.get("n_particles")
    if n_particles:
        outcome.append("%s particles" % _format_number(n_particles))
    if outcome:
        line += " — " + " / ".join(outcome)
    return line


def draft_methods_paragraph(ordered_jobs, job_options, job_stats):
    """`ordered_jobs`: job ids root→final, in the order they should be
    described. `job_options`/`job_stats`: {job_id: dict}. Returns a short
    multi-line draft — one line per job — meant as a starting point for a
    methods section, not a finished paragraph."""
    return "\n".join(
        job_sentence(job_id, job_options.get(job_id), job_stats.get(job_id))
        for job_id in ordered_jobs
    )
