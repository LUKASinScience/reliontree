"""Plan file -> new RELION jobs. A plan is a list of steps, each a diff
against an existing job (or an earlier step):

    {"steps": [{"id": "c4", "from": "Class3D/job021", "set": {"nr_classes": 4}},
               {"id": "sw", "from": "Class3D/job021", "sweep": {"nr_iter": [25, 50]}},
               {"id": "r",  "from": "Refine3D/job030", "set": {"fn_img": "{{c4}}/particles.star"}}]}

`check` is a pure dry run. `apply` registers the jobs as *Scheduled* through
RELION's own `relion_pipeliner --addJobFromStar` (never touches
default_pipeline.star itself) and runs nothing. Pure stdlib.
"""

import itertools
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from .relion_artifacts import parse_job_options
except ImportError:
    from relion_artifacts import parse_job_options

_REF = re.compile(r"\{\{(\w+)\}\}")
_ROW = re.compile(r"^(\w+)(\s+)(.*)$")


def expand_sweeps(steps):
    """Turn each `sweep` step into one plain step per combination."""
    out = []
    for st in steps:
        sweep = st.get("sweep")
        if not sweep:
            out.append(st)
            continue
        keys = sorted(sweep)
        for combo in itertools.product(*(sweep[k] for k in keys)):
            tag = "_".join("%s%s" % (k, v) for k, v in zip(keys, combo))
            new = {k: v for k, v in st.items() if k != "sweep"}
            new["id"] = "%s_%s" % (st["id"], tag)
            new["set"] = {**st.get("set", {}), **dict(zip(keys, combo))}
            if st.get("alias"):
                new["alias"] = "%s_%s" % (st["alias"], tag)
            out.append(new)
    return out


def _override(text, overrides):
    """Replace option values in a job.star text; returns (text, unknown_keys)."""
    seen, lines = set(), []
    for line in text.splitlines():
        m = _ROW.match(line)
        if m and m.group(1) in overrides:
            seen.add(m.group(1))
            line = '%s%s"%s"' % (m.group(1), m.group(2), overrides[m.group(1)])
        elif line.strip().startswith("_rlnJobIsContinue"):
            line = "_rlnJobIsContinue                             0"
        lines.append(line)
    return "\n".join(lines) + "\n", sorted(set(overrides) - seen)


def resolve(project, plan):
    """Dry run. Returns [{id, from, alias, text, changed, errors}] in plan order.
    `changed` is {key: (old, new)} against the source; `errors` lists problems
    (missing source, unknown option key, dangling {{ref}})."""
    project = Path(project)
    done, rows = {}, []
    for st in expand_sweeps(plan.get("steps", [])):
        src, errors = st.get("from", ""), []
        if src in done:
            text, base = done[src]["text"], done[src]["options"]
        else:
            star = project / src / "job.star"
            if not star.is_file():
                rows.append({"id": st["id"], "from": src, "alias": st.get("alias", ""),
                             "text": "", "changed": {}, "errors": ["source %s has no job.star" % src]})
                continue
            text, base = star.read_text(encoding="utf-8", errors="ignore"), parse_job_options(project / src)
        sets = {k: str(v) for k, v in st.get("set", {}).items()}
        for v in sets.values():
            errors += ["unknown step {{%s}}" % r for r in _REF.findall(v) if r not in done and r != st["id"]]
        text, unknown = _override(text, sets)
        errors += ["%s has no option '%s'" % (src, k) for k in unknown]
        changed = {k: (base.get(k), v) for k, v in sets.items() if base.get(k) != v}
        done[st["id"]] = {"text": text, "options": {**base, **sets}}
        rows.append({"id": st["id"], "from": src, "alias": st.get("alias", ""),
                     "text": text, "changed": changed, "errors": errors})
    return rows


def _jobdirs(project):
    return {"%s/%s" % (p.parent.name, p.name) for p in project.glob("*/job[0-9]*") if p.is_dir()}


def apply(project, rows, pipeliner="relion_pipeliner"):
    """Register every row as a Scheduled job; returns {step_id: 'Type/jobNNN'}.
    Stops at the first failure (earlier steps stay registered)."""
    project = Path(project)
    exe = shutil.which(pipeliner)
    if exe is None:
        raise ValueError("relion_pipeliner not on PATH (part of a RELION install)")
    if (project / ".relion_lock").exists():
        raise ValueError(".relion_lock present: a RELION GUI is open or crashed; close it first")
    made = {}
    for row in rows:
        text = _REF.sub(lambda m: made[m.group(1)], row["text"])
        before = _jobdirs(project)
        with tempfile.TemporaryDirectory(dir=str(project)) as tmp:
            star = Path(tmp) / "job.star"
            star.write_text(text, encoding="utf-8")
            args = [exe, "--addJobFromStar", str(star)]
            if row["alias"]:
                args += ["--setJobAlias", row["alias"]]
            proc = subprocess.run(args, cwd=str(project), capture_output=True, text=True, timeout=120)
        new = sorted(_jobdirs(project) - before)
        if not new:
            raise ValueError("pipeliner did not add step %s: %s" % (row["id"], (proc.stderr or proc.stdout).strip()[-200:]))
        made[row["id"]] = new[-1]
    return made


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
