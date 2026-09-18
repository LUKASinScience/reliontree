"""Turning a RELION job lineage into a plain table (CSV/Markdown) for a
methods section or supplementary material — independent of the Job Tree
diagram. Pure — no Qt/ChimeraX dependency."""

import csv
import io

COLUMNS = ["job", "type", "state", "parents", "resolution_angstrom", "n_particles"]
HEADERS = ["Job", "Type", "State", "Parent(s)", "Resolution (Å)", "Particles"]


def history_rows(ordered_jobs, job_artifacts, job_parents, job_stats):
    """One plain dict per job, in `ordered_jobs`' order — easy to test and
    to feed to either table writer below."""
    rows = []
    for job_id in ordered_jobs:
        fam = job_id.split("/")[0]
        artifacts = job_artifacts.get(job_id) or {}
        stats = job_stats.get(job_id) or {}
        parents = sorted(job_parents.get(job_id, ()))
        rows.append({
            "job": job_id,
            "type": fam,
            "state": artifacts.get("state", "unknown"),
            "parents": ", ".join(parents),
            "resolution_angstrom": stats.get("resolution_angstrom"),
            "n_particles": stats.get("n_particles"),
        })
    return rows


def _cell(row, column):
    value = row.get(column)
    if value is None:
        return ""
    if column == "resolution_angstrom":
        return "%.1f" % value
    if column == "n_particles":
        return format(value, ",")
    return str(value)


def rows_to_csv(rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    for row in rows:
        writer.writerow([_cell(row, c) for c in COLUMNS])
    return buf.getvalue()


def rows_to_markdown(rows):
    lines = [
        "| " + " | ".join(HEADERS) + " |",
        "|" + "|".join("---" for _ in HEADERS) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row, c) for c in COLUMNS) + " |")
    return "\n".join(lines)
