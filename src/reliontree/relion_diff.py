"""Parameter diffing across jobs — comparing two jobs' recorded options,
comparing N sibling jobs at once, and answering "why does this job exist"
(parent + siblings + what changed from the parent). All pure dict/set
operations over data `build_tree()` already computed (`options`,
`parents`) — no new file parsing, no dependency. Pure stdlib."""

try:
    from .relion_treebuild import job_type
except ImportError:
    from relion_treebuild import job_type


def diff_options(options_a, options_b):
    """Compare two jobs' {variable: value} option dicts (as parsed by
    relion_artifacts.parse_job_options). Returns
    {"changed": {key: (value_in_a, value_in_b)}, "unchanged": {key: value}}
    — a key present in only one side counts as changed, with None standing
    in for "not set" on the other side."""
    keys = sorted(set(options_a) | set(options_b))
    changed, unchanged = {}, {}
    for key in keys:
        value_a, value_b = options_a.get(key), options_b.get(key)
        if value_a != value_b:
            changed[key] = (value_a, value_b)
        else:
            unchanged[key] = value_a
    return {"changed": changed, "unchanged": unchanged}


def diff_many_options(jobs_options):
    """Compare more than two jobs at once (e.g. Refine3D siblings under the
    same Select job) — `jobs_options`: {job_id: options_dict}. Returns
    {"varying": {key: {job_id: value}}, "constant": {key: value}}: a
    parameter is "constant" only if every job in the group has the exact
    same value for it (including all having it unset)."""
    if not jobs_options:
        return {"varying": {}, "constant": {}}
    keys = sorted(set().union(*(opts.keys() for opts in jobs_options.values())))
    varying, constant = {}, {}
    for key in keys:
        values = {job: opts.get(key) for job, opts in jobs_options.items()}
        if len(set(values.values())) > 1:
            varying[key] = values
        else:
            constant[key] = next(iter(values.values()))
    return {"varying": varying, "constant": constant}


def job_context(tree, job):
    """"Why does this job exist?" for `job`: its parent(s), its siblings
    (other jobs sharing at least one of those parents), and what changed
    in its own options compared to its (first, if several) parent's
    options. `diff_from_parent` is None when the job has no parent (e.g.
    an Import job), the parent isn't in `tree`, or the parent is a
    different job type — a Select job's options don't share a schema with
    the Class3D job it feeds, so diffing them is noise, not signal; only
    same-type parent/child pairs (e.g. Refine3D from Refine3D) get a
    meaningful diff. Purely descriptive — the caller decides what to call
    this out as, if anything ("likely purpose" is a human/heuristic
    judgment call, not something computed here)."""
    parents = sorted(tree["parents"].get(job, ()))
    siblings = sorted(
        other for other, other_parents in tree["parents"].items()
        if other != job and set(other_parents) & set(parents)
    )
    diff_from_parent = None
    diff_parent = None
    if parents:
        # Prefer a same-type parent if the job has more than one (e.g. a
        # Refine3D job commonly takes both a mask and a previous Refine3D
        # job as inputs) -- picking the first one alphabetically would
        # often land on the differently-typed one and hide a real,
        # meaningful diff.
        same_type = [p for p in parents if job_type(p) == job_type(job)]
        diff_parent = same_type[0] if same_type else parents[0]
        parent_options = tree["options"].get(diff_parent)
        job_options = tree["options"].get(job)
        if (parent_options is not None and job_options is not None
                and job_type(diff_parent) == job_type(job)):
            diff_from_parent = diff_options(parent_options, job_options)
    return {
        "parents": parents, "siblings": siblings,
        "diff_from_parent": diff_from_parent, "diff_parent": diff_parent,
    }
