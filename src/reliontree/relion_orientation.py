"""Angular distribution of a 3D job from RELION's own `*_angdist.bild` files -- no particle table, no numpy.

RELION writes, per class and iteration, a Chimera marker file with one cylinder per occupied direction bin:
`.color r g b` then `.cylinder x1 y1 z1 x2 y2 z2 radius`, the cylinder starting on a sphere around the box
centre and pointing outwards, its length proportional to the number of particles. Directions that hold no
particles have no cylinder at all, which is exactly the gap you want to see. Pure stdlib."""

import math
import re
from pathlib import Path

_CYL = re.compile(r"^\.cylinder\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+\S+\s*$", re.MULTILINE)


def _fit_sphere_center(points):
    """Centre of the sphere through `points` (least squares, 4x4 normal equations). Needed because the box centre is
    not in the file and the mean of the points is biased when the directions are unevenly occupied."""
    a = [[0.0] * 5 for _ in range(4)]   # augmented [A | b] of  2 p.c + k = |p|^2  with unknowns (cx, cy, cz, k)
    for x, y, z in points:
        row = (2 * x, 2 * y, 2 * z, 1.0)
        rhs = x * x + y * y + z * z
        for i in range(4):
            for j in range(4):
                a[i][j] += row[i] * row[j]
            a[i][4] += row[i] * rhs
    for col in range(4):                # Gauss-Jordan with partial pivoting
        piv = max(range(col, 4), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise ValueError("directions do not span a sphere")
        a[col], a[piv] = a[piv], a[col]
        for r in range(4):
            if r != col:
                f = a[r][col] / a[col][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[col])]
    return tuple(a[i][4] / a[i][i] for i in range(3))


def parse_bild(text):
    """[(x, y, z, weight)] unit directions with weights relative to the busiest bin (0..1], or [] when there is
    nothing usable. Capped by the file's own size (a few thousand cylinders)."""
    cyls = [tuple(float(v) for v in m.groups()) for m in _CYL.finditer(text)]
    if len(cyls) < 4:
        return []
    starts = [c[:3] for c in cyls]
    try:
        centre = _fit_sphere_center(starts)
    except ValueError:
        return []
    out, longest = [], 0.0
    for x1, y1, z1, x2, y2, z2 in cyls:
        d = (x1 - centre[0], y1 - centre[1], z1 - centre[2])
        norm = math.sqrt(sum(v * v for v in d))
        length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)
        if norm == 0:
            continue
        out.append((d[0] / norm, d[1] / norm, d[2] / norm, length))
        longest = max(longest, length)
    if longest == 0:
        return []
    return [(x, y, z, w / longest) for x, y, z, w in out]


def _class_files(job_dir):
    """{class number: newest angdist.bild}: final `run_classNNN_angdist.bild` of a finished job, else the highest
    iteration; for a Refine3D job (two halves) the file of half 1."""
    found = {}
    for path in Path(job_dir).glob("run*_angdist.bild"):
        m = re.fullmatch(r"run(?:_it(\d+))?(?:_half([12]))?_class(\d+)_angdist\.bild", path.name)
        if not m:
            continue
        it = -1 if m.group(1) is None else int(m.group(1))
        key = (1 if m.group(1) is None else 0, it, 1 if m.group(2) != "2" else 0)   # final file wins, then iteration, then half 1
        number = int(m.group(3))
        if number not in found or key > found[number][0]:
            found[number] = (key, path)
    return {n: p for n, (_, p) in found.items()}


def job_orientation(job_dir, class_number=None):
    """{"classes": [numbers], "class": n, "source": filename, "bins": [[x, y, z, weight], ...]} or None.
    Directions are unit vectors in the reference's frame (the one RELION's bild uses), weights relative to the busiest bin."""
    files = _class_files(job_dir)
    if not files:
        return None
    number = class_number if class_number in files else min(files)
    try:
        bins = parse_bild(files[number].read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return None
    if not bins:
        return None
    return {"classes": sorted(files), "class": number, "source": files[number].name,
            "bins": [[round(x, 3), round(y, 3), round(z, 3), round(w, 3)] for x, y, z, w in bins]}


def has_orientation(job_dir):
    """Cheap check (no parsing): does this job have any angular-distribution file?"""
    try:
        return next(Path(job_dir).glob("run*_angdist.bild"), None) is not None
    except OSError:
        return False
