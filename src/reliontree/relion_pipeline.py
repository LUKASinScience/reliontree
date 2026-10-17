import logging
import re
import shlex
from collections import defaultdict, deque
from pathlib import Path


def parse_pipeline_star(text):
    """Extract process and edge tables from a pipeline STAR file."""
    # RELION >= 4 names the type/status columns `...TypeLabel` / `...StatusLabel` (text); RELION 3.x wrote
    # `...Type` / `...Status` as numbers. Both describe the same table.
    need_proc  = ({"_rlnPipeLineProcessName", "_rlnPipeLineProcessTypeLabel", "_rlnPipeLineProcessStatusLabel"},
                  {"_rlnPipeLineProcessName", "_rlnPipeLineProcessType", "_rlnPipeLineProcessStatus"})
    need_efrom = {"_rlnPipeLineEdgeFromNode", "_rlnPipeLineEdgeProcess"}
    need_eto   = {"_rlnPipeLineEdgeProcess",  "_rlnPipeLineEdgeToNode"}
    out = {"processes": [], "e_from": [], "e_to": []}
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip().lower() == "loop_":
            i += 1
            cols = []
            while i < n and lines[i].lstrip().startswith("_"):
                cols.append(lines[i].split()[0]); i += 1
            rows = []
            while i < n and lines[i].strip() \
                    and not lines[i].lstrip().startswith("_") \
                    and not lines[i].strip().lower().startswith("data_") \
                    and lines[i].strip().lower() != "loop_":
                try:
                    parts = shlex.split(lines[i].strip(), posix=True)
                except ValueError:
                    parts = re.split(r"\s+", lines[i].strip())
                if len(parts) >= len(cols):
                    rows.append(parts[:len(cols)])
                i += 1
            cset = set(cols)
            make = lambda: [dict(zip(cols, r)) for r in rows]
            if any(n.issubset(cset) for n in need_proc):  out["processes"].extend(make())
            elif need_efrom.issubset(cset): out["e_from"].extend(make())
            elif need_eto.issubset(cset):   out["e_to"].extend(make())
            continue
        i += 1
    return out


def load_pipeline(project):
    """Read default_pipeline.star and per-job star files under `project`
    (a pathlib.Path). Returns (procs, node_to_prod, proc_to_in)."""
    def read(p):
        try:
            return Path(p).read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            # a missing per-job star file is normal; an existing but unreadable one would silently drop jobs from the lineage
            if Path(p).exists():
                logging.getLogger(__name__).warning("could not read %s: %s", p, exc)
            return ""

    procs = set()
    e_from, e_to = [], []

    def ingest(text):
        t = parse_pipeline_star(text)
        for p in t["processes"]:
            name = p.get("_rlnPipeLineProcessName", "").strip().rstrip("/")
            if name:
                procs.add(name)
        e_from.extend(t["e_from"])
        e_to.extend(t["e_to"])

    ps = project / "default_pipeline.star"
    if ps.exists():
        ingest(read(ps))
    for fam in sorted([d for d in project.iterdir() if d.is_dir()]):
        for jd in fam.glob("job*/"):
            for fn in ("job_pipeline.star", "default_pipeline.star"):
                f = jd / fn
                if f.exists():
                    ingest(read(f))

    node_to_prod = defaultdict(set)
    proc_to_in   = defaultdict(set)
    for r in e_to:
        proc = r.get("_rlnPipeLineEdgeProcess", "").strip().rstrip("/")
        node = r.get("_rlnPipeLineEdgeToNode",  "").strip()
        if proc and node:
            node_to_prod[node].add(proc)
    for r in e_from:
        node = r.get("_rlnPipeLineEdgeFromNode", "").strip()
        proc = r.get("_rlnPipeLineEdgeProcess",  "").strip().rstrip("/")
        if proc and node:
            proc_to_in[proc].add(node)

    return procs, node_to_prod, proc_to_in


_PIPELINE_STATUS_CODE = {"0": "running", "1": "scheduled", "2": "succeeded", "3": "failed", "4": "aborted"}   # RELION 3.x
_PIPELINE_STATUS = {"succeeded": "succeeded", "failed": "failed", "running": "running",
                    "aborted": "aborted", "scheduled": "scheduled"}


def load_meta(project):
    """{job: {"alias": str, "status": str}} from default_pipeline.star's
    process table: RELION's own alias (e.g. `remove_junk_1`) and status
    label. Jobs only referenced from per-job pipeline files are absent."""
    try:
        text = (Path(project) / "default_pipeline.star").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    meta = {}
    for row in parse_pipeline_star(text)["processes"]:
        name = row.get("_rlnPipeLineProcessName", "").strip().rstrip("/")
        alias = row.get("_rlnPipeLineProcessAlias", "").strip().rstrip("/")
        alias = "" if alias in ("", "None") else alias.split("/")[-1]
        label = row.get("_rlnPipeLineProcessStatusLabel", "").strip().lower()
        status = _PIPELINE_STATUS.get(label) or _PIPELINE_STATUS_CODE.get(row.get("_rlnPipeLineProcessStatus", "").strip(), "")
        if name:
            meta[name] = {"alias": alias, "status": status,
                          "type": row.get("_rlnPipeLineProcessTypeLabel", "").strip().lower()}
    return meta


_SPA_ONLY_TYPES = ("relion.motioncorr", "relion.ctffind", "relion.autopick", "relion.class2d", "relion.manualpick")


def detect_experiment(meta, job_dirs):
    """Is this a subtomogram-averaging ("sta") or single-particle ("spa") project? Returns
    {"type": "sta" | "spa" | "unknown", "evidence": str}.

    Signals RELION itself writes: a process type label with "tomo" in it (relion.importtomo,
    relion.pseudosubtomo, relion.refine3d.tomo, ...) and `_rlnJobIsTomo 1` in a job.star. Any such signal makes the project
    STA; otherwise motion correction / CTF / 2D classification / picking jobs make it SPA. RELION 3.x pipelines have no
    type labels, they are SPA by definition (tomography came with RELION 4)."""
    tomo_labels = sorted({m["type"] for m in meta.values() if "tomo" in m.get("type", "")})
    tomo_flags = 0
    for job_dir in job_dirs:
        try:
            text = (Path(job_dir) / "job.star").read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"^_rlnJobIsTomo\s+1\s*$", text, re.MULTILINE):
            tomo_flags += 1
    if tomo_labels or tomo_flags:
        bits = []
        if tomo_labels:
            bits.append("job types " + ", ".join(tomo_labels[:3]))
        if tomo_flags:
            bits.append("%d job.star with _rlnJobIsTomo 1" % tomo_flags)
        return {"type": "sta", "evidence": "; ".join(bits)}
    spa = sorted({m["type"] for m in meta.values() if m.get("type") in _SPA_ONLY_TYPES})
    if spa:
        return {"type": "spa", "evidence": "job types " + ", ".join(spa[:3])}
    if meta and not any(m.get("type") for m in meta.values()):
        return {"type": "spa", "evidence": "RELION 3.x pipeline (no tomography before RELION 4)"}
    return {"type": "unknown", "evidence": "no tomography or single-particle specific job found"}


def build_parents(procs, node_to_prod, proc_to_in):
    parents = {p: set() for p in procs}
    for proc in procs:
        for node in proc_to_in.get(proc, ()):
            for par in node_to_prod.get(node, ()):
                if par != proc:
                    parents[proc].add(par)
    return parents


def upstream(selected, parents):
    """Return all upstream jobs of selected (inclusive)."""
    keep = {selected}
    q = deque([selected])
    while q:
        u = q.popleft()
        for p in parents.get(u, ()):
            if p not in keep:
                keep.add(p)
                q.append(p)
    sub = {k: {p for p in v if p in keep}
           for k, v in parents.items() if k in keep}
    return keep, sub


def limit_hops(selected, parents, max_hops):
    """A bounded version of `upstream()` — keep only jobs within
    `max_hops` upstream steps of `selected` (inclusive), for a "local
    view" of a large lineage. `max_hops` of `None` or <= 0 means
    unlimited, i.e. identical to `upstream(selected, parents)`."""
    if not max_hops or max_hops <= 0:
        return upstream(selected, parents)
    keep = {selected}
    frontier = {selected}
    for _ in range(max_hops):
        next_frontier = set()
        for u in frontier:
            for p in parents.get(u, ()):
                if p not in keep:
                    keep.add(p)
                    next_frontier.add(p)
        frontier = next_frontier
        if not frontier:
            break
    sub = {k: {p for p in v if p in keep}
           for k, v in parents.items() if k in keep}
    return keep, sub


_JOB_NUM_RE = re.compile(r"job(\d+)$")


def job_num(j):
    m = _JOB_NUM_RE.search(j)
    return int(m.group(1)) if m else 10 ** 9


def sort_by_job_number(jobs, reverse=False):
    """Sort job ids (e.g. "Class3D/job003") by their numeric suffix. RELION
    numbers jobs globally across the whole project (not per-family), so this
    is a correct "most recent first" ordering with `reverse=True` — no
    filesystem-mtime guessing needed."""
    return sorted(jobs, key=lambda j: (job_num(j), j), reverse=reverse)


def layers(selected, parents):
    """Assign BFS depth to each job → chronological layers root→selected."""
    memo = {}

    def depth(u):
        if u in memo:
            return memo[u]
        if not parents.get(u):
            memo[u] = 0
            return 0
        memo[u] = 1 + max(depth(p) for p in parents[u])
        return memo[u]

    for u in parents:
        depth(u)

    max_d = max(memo.values()) if memo else 0
    out = [[] for _ in range(max_d + 1)]
    for j, d in memo.items():
        out[d].append(j)
    for layer in out:
        layer.sort(key=lambda j: (job_num(j), j))
    return out
