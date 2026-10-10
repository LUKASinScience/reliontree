"""Optional notes other tools attach to jobs, shown as pills on cards and in
the job panel. The contract is just files, so reliontree stays dependency-free
and any tool can write them (relion-origin: QC signals, relion-copilot:
next-step proposals):

    <project>/.reliontree/annotations/<tool>.json

        {"Class3D/job004": [{"label": "R=0.82 clustered", "level": "warn",
                              "detail": "classes 2 and 4 look in one direction"}]}

`level` is one of good / warn / bad / info. One file per tool, so writers
never overwrite each other. Everything read here is untrusted: anything
malformed is skipped, text is length-capped (the HTML layer escapes it).
Pure stdlib."""

import json
from pathlib import Path

ANNOTATION_DIR = Path(".reliontree") / "annotations"
LEVELS = ("bad", "warn", "info", "good")        # sorted most severe first
MAX_PER_JOB, MAX_LABEL, MAX_DETAIL = 6, 48, 400


def _clean(entry, source):
    if not isinstance(entry, dict) or not isinstance(entry.get("label"), str) or not entry["label"].strip():
        return None
    level = entry.get("level")
    detail = entry.get("detail")
    return {
        "label": entry["label"].strip()[:MAX_LABEL],
        "level": level if level in LEVELS else "info",
        "detail": detail.strip()[:MAX_DETAIL] if isinstance(detail, str) else "",
        "source": source,
    }


def load_annotations(project):
    """{job: [{label, level, detail, source}]}, most severe first, from every
    `*.json` under `<project>/.reliontree/annotations/`. Missing dir -> {}."""
    out = {}
    folder = Path(project) / ANNOTATION_DIR
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return {}
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for job, entries in data.items():
            if not isinstance(job, str) or not isinstance(entries, list):
                continue
            for entry in entries:
                clean = _clean(entry, f.stem)
                if clean:
                    out.setdefault(job, []).append(clean)
    for job in out:
        out[job].sort(key=lambda a: LEVELS.index(a["level"]))
        del out[job][MAX_PER_JOB:]
    return out
