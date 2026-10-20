"""Assemble a RELION job lineage (pipeline graph + per-job artifacts/stats)
into plain data, and render it as SVG -- the shared, Qt/ChimeraX-free core
behind both `relion_cli.py` (a plain terminal) and `cmd.py` (the ChimeraX
command line). Pure stdlib only."""

import re
import struct
from pathlib import Path

from .relion_fsc import fsc_curves

try:
    from .relion_annotations import load_annotations
    from .relion_pipeline import load_pipeline, load_meta, detect_experiment, build_parents, upstream, limit_hops, layers as pipeline_layers
    from .relion_artifacts import scan_job_artifacts, job_stats, parse_job_options, list_class_maps, list_class_stack
    from .relion_tree_layout import layout_positions
    from .relion_mrc_thumb import mrc_slice_thumbnail
    from .relion_classes import class_history, class_selection, class_iter_thumbs, SETTLED_CHANGES, TINY_SHARE
except ImportError:
    from relion_annotations import load_annotations
    from relion_pipeline import load_pipeline, load_meta, detect_experiment, build_parents, upstream, limit_hops, layers as pipeline_layers
    from relion_artifacts import scan_job_artifacts, job_stats, parse_job_options, list_class_maps, list_class_stack
    from relion_tree_layout import layout_positions
    from relion_mrc_thumb import mrc_slice_thumbnail
    from relion_classes import class_history, class_selection, class_iter_thumbs, SETTLED_CHANGES, TINY_SHARE

CARD_W = 200
HEADER_H = 40          # colored bar + type label + job id line
FOOTER_LINE_H = 14     # each of the state / stats text lines below the grid
DETAILS_BTN_H = 20     # visible "Details" button strip at the bottom of every card
PADDING_BOTTOM = 6
ANNO_H = 18            # row of annotation pills (notes from relion-origin / relion-copilot ...)
ANNO_COLORS = {"bad": "#c62828", "warn": "#e65100", "info": "#546e7a", "good": "#2e7d32"}
MAX_ANNO_PILLS = 2
BADGE_H = 18           # row of 'latest result' / 'best resolution' pills under the header
ROW_GAP = 20
CHIP_H = 34            # row of small mask chips (thumbnail + id) at the bottom of a consumer card
CHIP_W = 58
CHIP_THUMB = 24
MAX_CHIPS = 3
MAX_CLASS_THUMBS = 12     # a 200-class Class2D job must not become a 4000 px tall card
CONV_H = 36            # convergence sparkline strip on Class2D/Class3D cards
TINY_CLASS_SHARE = TINY_SHARE      # a class below this share is dimmed: almost certainly an empty/junk class
CONV_SETTLED = SETTLED_CHANGES     # dashed "settled" level
SINGLE_THUMB_SIZE = 120
GRID_THUMB_SIZE = 56
GRID_COLS = 3
GRID_GAP = 4
_CLASS_NUM_RE = re.compile(r"class(\d+)\.mrc$", re.IGNORECASE)
STATE_COLORS = {
    "succeeded": "#2e7d32", "failed": "#c62828", "aborted": "#e65100",
    "running": "#1565c0", "unknown": "#616161", "scheduled": "#8e6a00", "missing": "#9e9e9e",
}
STATE_HINTS = {"missing": "job directory not found on disk (referenced by the pipeline)",
               "scheduled": "registered in the pipeline, not started yet"}
FINAL_TYPES = ("PostProcess", "Refine3D", "Class3D", "Class2D")  # what counts as "the result", best first
# cryoSPARC-style per-job-type accent colors (job cards there are colored by
# type, not by run state -- state is a separate badge/icon).
JOB_TYPE_COLORS = {
    "Import": "#8e24aa", "MotionCorr": "#3949ab", "CtfFind": "#00897b",
    "ManualPick": "#6d4c41", "AutoPick": "#6d4c41", "Extract": "#43a047",
    "Class2D": "#fb8c00", "Class3D": "#1e88e5", "InitialModel": "#3949ab",
    "Select": "#757575", "Refine3D": "#e53935", "MaskCreate": "#7cb342",
    "PostProcess": "#5e35b1", "LocalRes": "#00acc1", "CtfRefine": "#c0ca33",
    "Polish": "#d81b60", "Subtract": "#757575", "JoinStar": "#757575",
}
DEFAULT_TYPE_COLOR = "#616161"


def job_type(job):
    return job.split("/")[0]


_EXTERNAL_TOOLS = ("cryolo", "topaz", "janni", "warp", "isonet", "aretomo")


def job_label(job, options=None):
    """Card label: job type, but an External job is named after the tool
    in its `fn_exe` (crYOLO, Topaz, ...) when recognisable.
    ponytail: `fn_exe` is the RELION External option name, unverified on real data."""
    t = job_type(job)
    if t == "External":
        exe = (options or {}).get("fn_exe", "").lower()
        for tool in _EXTERNAL_TOOLS:
            if tool in exe:
                return "External: " + tool
    return t


def _class_number(path):
    m = _CLASS_NUM_RE.search(path.name)
    return int(m.group(1)) if m else None


def _stack_slices(path):
    """Range of Z-slices (= classes) in an MRC stack, from its header."""
    try:
        with open(path, "rb") as f:
            return range(struct.unpack("<3i", f.read(12))[2])
    except (OSError, struct.error):
        return range(0)


def _job_maps(job_dir, artifacts):
    """[(class_number_or_None, path), ...] for everything a card should show
    a thumbnail for: every per-class volume when a job has more than one
    (Class2D/Class3D-style jobs), else its single most relevant map
    (postprocessed > latest class/refine map > mask)."""
    stack = list_class_stack(job_dir)
    if stack is not None:
        n = max(1, len(_stack_slices(stack)))
        return [(i + 1, (stack, i)) for i in range(n)]
    classes = list_class_maps(job_dir)
    if len(classes) > 1:
        return [(_class_number(p), p) for p in classes]
    for key in ("postprocess_map", "latest_map", "mask"):
        path = artifacts.get(key)
        if path and path.is_file():
            return [(None, path)]
    return []


def pick_classes(tree, job, limit=MAX_CLASS_THUMBS):
    """Class numbers worth a thumbnail on `job`'s card: None (= all) when it has at most `limit` classes, else the
    classes a Select job kept first, then the largest ones -- what you would look at in a 200-class Class2D job."""
    hist = tree.get("classes", {}).get(job) or []
    shares = hist[-1]["shares"] if hist else []
    if len(shares) <= limit:
        return None
    keep = set(tree.get("chosen", {}).get(job, {}))
    for number in sorted(range(1, len(shares) + 1), key=lambda n: -shares[n - 1]):
        if len(keep) >= limit:
            break
        keep.add(number)
    return keep


def _job_thumbnails(job_dir, artifacts, keep=None):
    """[(class_number_or_None, data_uri), ...], skipping any map that
    fails to decode (unsupported MRC mode, truncated file, ...). `keep`: only these class numbers."""
    maps = _job_maps(job_dir, artifacts)
    if keep is not None:
        maps = [(n, p) for n, p in maps if n in keep]
    size = GRID_THUMB_SIZE if len(maps) > 1 else SINGLE_THUMB_SIZE
    out = []
    for num, path in maps:
        z = None
        if isinstance(path, tuple):
            path, z = path
        uri = mrc_slice_thumbnail(path, size=size, z=z)
        if uri:
            out.append((num, uri))
    return out


def build_tree(project_dir, selected=None, max_hops=None):
    """Return {"layers": [[job_id,...],...], "parents": {job: {parents}},
    "artifacts": {job: dict}, "stats": {job: dict}, "options": {job: dict},
    "job_dirs": {job: Path}} for the job lineage under `project_dir` (a
    RELION project directory, i.e. the one containing
    `default_pipeline.star`)."""
    project_dir = Path(project_dir)
    procs, node_to_prod, proc_to_in = load_pipeline(project_dir)
    parents = build_parents(procs, node_to_prod, proc_to_in)

    if selected:
        if selected not in parents:
            raise ValueError("job %r not found in pipeline under %s" % (selected, project_dir))
        _, parents = limit_hops(selected, parents, max_hops) if max_hops else upstream(selected, parents)

    # A MaskCreate job that something consumes is an accessory, not a lineage step:
    # it is drawn as a small chip on its consumer instead of a card of its own.
    has_child = {p for ps in parents.values() for p in ps}
    masks = sorted(j for j in parents if job_type(j) == "MaskCreate" and j in has_child)
    mset = set(masks)
    chips = {}
    layer_parents = {}
    for j, ps in parents.items():
        if j in mset:
            continue
        layer_parents[j] = {p for p in ps if p not in mset}
        if ps & mset:
            chips[j] = sorted(ps & mset)
    lyrs = pipeline_layers(None, layer_parents)  # `selected` arg is unused by layers()
    parents = {**layer_parents, **{m: parents[m] for m in masks}}

    layered = [j for layer in lyrs for j in layer]
    jobs = masks + layered
    artifacts, stats, options, job_dirs, classes = {}, {}, {}, {}, {}
    for job in jobs:
        job_dir = project_dir / job
        job_dirs[job] = job_dir
        artifacts[job] = scan_job_artifacts(job_dir)
        stats[job] = job_stats(job_dir)
        options[job] = parse_job_options(job_dir)
        classes[job] = class_history(job_dir) if job_type(job) in ("Class2D", "Class3D") else []

    # Select-classes jobs: which of the parent classification's classes were kept
    selection = {}
    for job in jobs:
        if job_type(job) != "Select":
            continue
        for parent in sorted(parents.get(job, [])):
            hist = classes.get(parent)
            flags = class_selection(job_dirs[job], len(hist[-1]["shares"])) if hist else None
            if flags:
                selection[job] = {"parent": parent, "flags": flags}
                break

    # which classes of a classification were kept by a Select job: {class job: {class number: [select jobs]}}
    chosen = {}
    for job, sel in selection.items():
        for i, kept in enumerate(sel["flags"]):
            if kept:
                chosen.setdefault(sel["parent"], {}).setdefault(i + 1, []).append(job)

    meta = load_meta(project_dir)
    alias, notes = {}, {}
    for job in jobs:
        alias[job] = meta.get(job, {}).get("alias", "")
        st = artifacts[job]
        if not job_dirs[job].is_dir():
            st["state"] = "missing"
        elif not st.get("state_from_marker") and meta.get(job, {}).get("status"):
            st["state"] = meta[job]["status"]   # RELION's own status label beats the run.out guess (and fills "unknown")
        notes[job] = user_notes(job_dirs[job])

    annotations = {j: a for j, a in load_annotations(project_dir).items() if j in job_dirs}
    experiment = detect_experiment({j: meta[j] for j in meta if j in job_dirs}, job_dirs.values())

    fsc_res = lambda j: (fsc_curves(job_dirs[j]) or {}).get("resolution")
    final, best, main, side = find_main_path(layered, parents, artifacts, stats, fsc_res)
    best_fsc = fsc_res(best) if best and job_type(best) in ("PostProcess", "Refine3D") else None
    return {
        "best_fsc": best_fsc,
        "selection": selection, "chosen": chosen,
        "layers": lyrs, "parents": parents,
        "artifacts": artifacts, "stats": stats, "options": options,
        "job_dirs": job_dirs, "classes": classes,
        "alias": alias, "notes": notes, "chips": chips, "masks": masks, "annotations": annotations, "experiment": experiment,
        "latest": final, "best": best, "main": main, "side": side,
    }


def user_notes(job_dir):
    """What a person typed into a job's note.txt. RELION also logs every
    executed command there inside a `++++ Executing ... ++++` block; that
    block is dropped."""
    try:
        text = (job_dir / "note.txt").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    keep, in_block = [], False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("++++ Executing"):
            in_block = True
        elif in_block:
            in_block = t != "++++"
        elif t:
            keep.append(line.rstrip())
    return "\n".join(keep)[:1000]


def find_main_path(jobs, parents, artifacts, stats, fsc_res=None):
    """(latest, best, main, side): `latest` = highest-numbered succeeded job
    of the most "final" type present (PostProcess > Refine3D > Class3D >
    Class2D); `best` = lowest resolution_angstrom among succeeded
    Refine3D/PostProcess jobs; `main` = latest + all its ancestors;
    `side` = dead ends: no children, not on the main path (only when a
    latest exists)."""
    def num(j):
        m = re.search(r"(\d+)$", j)
        return int(m.group(1)) if m else 0
    ok = [j for j in jobs if artifacts[j]["state"] == "succeeded"]
    latest = None
    for t in FINAL_TYPES:
        cand = [j for j in ok if job_type(j) == t]
        if cand:
            latest = max(cand, key=num)
            break
    res = [j for j in ok if job_type(j) in ("Refine3D", "PostProcess") and stats[j].get("resolution_angstrom")]
    best = None
    if res:
        low = min(stats[j]["resolution_angstrom"] for j in res)
        tied = [j for j in res if stats[j]["resolution_angstrom"] == low]
        # RELION's shell value is quantised, ties are common: interpolated FSC crossing decides, then the newer job
        cross = lambda j: (fsc_res(j) if fsc_res and len(tied) > 1 else None) or float("inf")
        best = min(tied, key=lambda j: (cross(j), -num(j)))
    main, todo = set(), [latest] if latest else []
    while todo:
        j = todo.pop()
        if j not in main:
            main.add(j)
            todo.extend(parents.get(j, ()))
    has_child = {p for ps in parents.values() for p in ps}
    side = {j for j in jobs if latest and j not in main and j not in has_child}
    return latest, best, main, side


def ordered_jobs(tree):
    return list(tree.get("masks", [])) + [j for layer in tree["layers"] for j in layer]


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _convergence(tree, job):
    """[(iter, fraction switching class)] without the meaningless it0 row;
    [] when the job has fewer than 2 points to draw."""
    pts = [(h["iter"], h["changes_classes"]) for h in tree.get("classes", {}).get(job, [])
           if h["changes_classes"] is not None and h["iter"] > 0]
    return pts if len(pts) > 1 else []


def _conv_svg(x, y, w, h, pts):
    """Inline sparkline: line = share of particles switching class per
    iteration, dashed = CONV_SETTLED, text = latest value."""
    ymax = max(CONV_SETTLED * 1.2, max(v for _, v in pts))
    px = lambda i: x + i * w / (len(pts) - 1)
    py = lambda v: y + h - v / ymax * h
    line = " ".join("%.1f,%.1f" % (px(i), py(v)) for i, (_, v) in enumerate(pts))
    last = pts[-1][1]
    color = "#2e7d32" if last <= CONV_SETTLED else "#e65100"
    return ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#bbb" stroke-dasharray="2 2"/>'
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="1.5"/>'
            '<text x="%.1f" y="%.1f" fill="%s" font-size="10" text-anchor="end">%.1f%% switch/it%s</text>' %
            (x, py(CONV_SETTLED), x + w, py(CONV_SETTLED), line, color, x + w, y - 2, color, last * 100,
             "" if last <= CONV_SETTLED else " \u00b7 not converged"))


def _wrap_label(segments, max_chars):
    """Greedy-wrap the ' / '-joined footer segments onto lines that fit the card; a segment is never split."""
    lines, cur = [], ""
    for seg in segments:
        trial = seg if not cur else cur + " / " + seg
        if cur and len(trial) > max_chars:
            lines.append(cur)
            cur = seg
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _card_layout(tree, job, thumbs):
    """Precompute everything geometry-dependent for one card so the size
    used for column layout and the size actually drawn agree exactly --
    two places computing slightly different heights is what let footer
    text spill past the card border before."""
    stats = tree["stats"].get(job, {})
    label2 = []
    if stats.get("resolution_angstrom"):
        bf = tree.get("best_fsc") if job == tree.get("best") else None
        label2.append("%.1f A shell" % stats["resolution_angstrom"] if bf else "%.1f A" % stats["resolution_angstrom"])
        if bf:
            label2.append("%.2f A FSC" % bf)
    if stats.get("n_particles"):
        label2.append("%s particles" % format(stats["n_particles"], ","))

    sel = tree.get("selection", {}).get(job)
    hist = tree.get("classes", {}).get(sel["parent"]) if sel else None
    if sel and hist:
        kept = [i for i, f in enumerate(sel["flags"]) if f and i < len(hist[-1]["shares"])]
        names = ", ".join("C%d" % (i + 1) for i in kept) if len(kept) <= 4 else "%d of %d classes" % (len(kept), len(hist[-1]["shares"]))
        label2.insert(0, "kept %s (%.0f%%)" % (names, 100 * sum(hist[-1]["shares"][i] for i in kept)))

    shares = (tree.get("classes", {}).get(job) or [{"shares": []}])[-1]["shares"]
    if thumbs and len(shares) > len(thumbs) > 1:
        label2.append("%d of %d classes" % (len(thumbs), len(shares)))
    n = len(thumbs)
    if n == 0:
        cols = 0
        thumb_size = 0
        grid_w = grid_h = 0
    else:
        thumb_size = SINGLE_THUMB_SIZE if n == 1 else GRID_THUMB_SIZE
        cols = 1 if n == 1 else min(GRID_COLS, n)
        rows = -(-n // cols)  # ceil
        grid_w = cols * thumb_size + (cols - 1) * GRID_GAP
        grid_h = rows * thumb_size + (rows - 1) * GRID_GAP

    badges = []
    if job == tree.get("latest"):
        badges.append(("\u2605 latest result", "#1565c0"))
    if job == tree.get("best"):
        badges.append(("\u2605 best resolution", "#2e7d32"))
    badge_h = BADGE_H if badges else 0
    chip_h = CHIP_H if tree.get("chips", {}).get(job) else 0
    anno_h = ANNO_H if tree.get("annotations", {}).get(job) else 0

    conv = _convergence(tree, job)
    compact = tree["artifacts"].get(job, {}).get("state") == "missing"   # nothing on disk to show
    label_lines = _wrap_label(label2, int((CARD_W - 16) / 5.6))   # ~5.6 px per character at font-size 10-11
    height = (HEADER_H + badge_h + anno_h + chip_h + grid_h + FOOTER_LINE_H + FOOTER_LINE_H * len(label_lines) +
              (CONV_H if conv else 0) + PADDING_BOTTOM + (0 if compact else DETAILS_BTN_H))
    return {
        "label2": label2, "label_lines": label_lines, "conv": conv, "cols": cols, "thumb_size": thumb_size,
        "grid_w": grid_w, "grid_h": grid_h, "height": height,
        "badges": badges, "badge_h": badge_h, "anno_h": anno_h, "chip_h": chip_h, "compact": compact,
    }


def route_edges(tree, pos, card_sizes):
    """[(parent, child, svg_path_d, on_main_path, skips_generations)] with orthogonal edges that
    never cross a card: an edge between neighbouring generations jogs in the
    gap between the two rows; an edge that skips generations drops through a
    free vertical lane beside the cards of the generations it skips. Also
    returns the rightmost x any lane needs."""
    layer_of = {j: i for i, layer in enumerate(tree["layers"]) for j in layer}
    row_top, row_bot = {}, {}
    for j, i in layer_of.items():
        if j in pos:
            row_top[i] = min(row_top.get(i, 1e9), pos[j][1])
            row_bot[i] = max(row_bot.get(i, -1), pos[j][1] + card_sizes[j][1])
    main = tree.get("main", set())
    edges, max_x = [], 0
    for job, ps in tree["parents"].items():
        if job not in pos:
            continue
        x2, y2 = pos[job][0] + CARD_W / 2, pos[job][1]
        li = layer_of[job]
        for parent in sorted(ps):
            if parent not in pos:
                continue
            x1, y1 = pos[parent][0] + CARD_W / 2, pos[parent][1] + card_sizes[parent][1]
            lp = layer_of[parent]
            ya, yb = row_bot[lp] + ROW_GAP / 2, row_top[li] - ROW_GAP / 2
            if li - lp <= 1:
                d = "M %.1f %.1f V %.1f H %.1f V %.1f" % (x1, y1, (ya + yb) / 2, x2, y2)
            else:
                blocked = [(pos[j][0] - 6, pos[j][0] + CARD_W + 6)
                           for j in pos if lp < layer_of[j] < li]
                lanes = [pos[j][0] + CARD_W + 8 for j in pos if lp < layer_of[j] < li] or [x2]
                free = [g for g in lanes if not any(a <= g <= b for a, b in blocked)]
                gx = min(free, key=lambda g: abs(g - x2)) if free else max(lanes)
                max_x = max(max_x, gx)
                d = "M %.1f %.1f V %.1f H %.1f V %.1f H %.1f V %.1f" % (x1, y1, ya, gx, yb, x2, y2)
            edges.append((parent, job, d, parent in main and job in main, li - lp > 1))
    return edges, max_x


def render_svg(tree, fit=False):
    """A cryoSPARC-card-style SVG rendering of the job tree: one card per
    job, colored header by job type, a state badge, and central-slice
    thumbnails of its output map(s) -- a grid of every per-class volume for
    a multi-class Class2D/Class3D job, one big thumbnail otherwise.
    Connectors between parent and child are orthogonal (vertical/
    horizontal segments only, no diagonals) -- each generation is a row, so
    a connector drops straight down from the parent, jogs sideways at the
    row's midline, then drops straight into the child. Card height is
    computed once per job from its actual content (header + thumbnail grid
    + text lines), so text never overflows the border. Not a pixel-match
    for the in-app Qt dialog's export -- a readable, portable equivalent
    for headless/terminal use."""
    jobs = [j for layer in tree["layers"] for j in layer]  # masks are chips, not cards
    thumbs = {
        j: _job_thumbnails(tree["job_dirs"][j], tree["artifacts"].get(j, {}), pick_classes(tree, j))
        for j in jobs
    }
    for j in tree.get("selection", {}):  # Select: no thumbs, the parent card already shows the kept classes
        thumbs[j] = []
    chip_thumbs = {}
    for m in {m for ms in tree.get("chips", {}).values() for m in ms[:MAX_CHIPS]}:
        maps = _job_maps(tree["job_dirs"][m], tree["artifacts"].get(m, {}))
        path = maps[0][1] if maps else None
        chip_thumbs[m] = mrc_slice_thumbnail(path, size=CHIP_THUMB) if path else None
    layouts = {j: _card_layout(tree, j, thumbs[j]) for j in jobs}
    card_sizes = {j: (CARD_W, layouts[j]["height"]) for j in jobs}
    pos = layout_positions(tree["layers"], card_sizes)

    def bottom(job):
        x, y = pos[job]
        return x + CARD_W / 2, y + card_sizes[job][1]

    def top(job):
        x, y = pos[job]
        return x + CARD_W / 2, y

    layer_idx = {j: i for i, layer in enumerate(tree["layers"]) for j in layer}
    edges, lane_x = route_edges(tree, pos, card_sizes)
    width = int(max(max((x + CARD_W for x, y in pos.values()), default=0), lane_x)) + 20
    height = max((y + card_sizes[j][1] for j, (x, y) in pos.items()), default=0) + 20

    size_attrs = ('width="100%%" height="100%%" viewBox="0 0 %d %d" data-w="%d" data-h="%d"' % (width, height, width, height)
                  if fit else 'width="%d" height="%d"' % (width, height))
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" %s '
        'font-family="sans-serif" font-size="12">' % size_attrs,
        '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto">'
        '<path d="M0 0L10 5L0 10z" fill="#999"/></marker>'
        '<marker id="arr-main" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto">'
        '<path d="M0 0L10 5L0 10z" fill="#1565c0"/></marker>'
        '<marker id="arr-b" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto">'
        '<path d="M0 0L10 5L0 10z" fill="#e65100"/></marker>'
        '<marker id="arr-ab" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto">'
        '<path d="M0 0L10 5L0 10z" fill="#7b1fa2"/></marker></defs>',
        '<rect width="100%" height="100%" fill="white"/>',
    ]

    for parent, job, d, is_main, is_skip in sorted(edges, key=lambda e: e[3]):  # main-path edges on top
        # edges that skip generations are thin and dashed so they read as "also used by", not as the flow
        parts.append('<path class="edge%s" data-from="%s" data-to="%s" d="%s" fill="none" '
                     'stroke="%s" stroke-width="%s"%s marker-end="url(#%s)"/>' %
                     (" main" if is_main else "", _esc(parent), _esc(job), d,
                      "#1565c0" if is_main else "#999", "1.2" if is_skip else "2.2" if is_main else "1.5",
                      ' stroke-dasharray="5 4"' if is_skip else "", "arr-main" if is_main else "arr"))

    for job, (x, y) in pos.items():
        lay = layouts[job]
        h = lay["height"]
        state = tree["artifacts"].get(job, {}).get("state", "unknown")
        state_color = STATE_COLORS.get(state, STATE_COLORS["unknown"])
        type_color = JOB_TYPE_COLORS.get(job_type(job), DEFAULT_TYPE_COLOR)

        jid = job.split("/", 1)[1] if "/" in job else job
        alias = tree.get("alias", {}).get(job, "")
        cls = "job-card" + (" main" if job in tree.get("main", ()) else "") + (" side" if job in tree.get("side", ()) else "")
        parts.append('<g id="card-%s" class="%s" data-job="%s" data-x="%.1f" data-y="%.1f" data-w="%d" data-h="%d" data-layer="%d"%s>' %
                      (_esc(job), cls, _esc(job), x, y, CARD_W, h, layer_idx.get(job, 0),
                       ' opacity="0.55"' if job in tree.get("side", ()) else ""))
        parts.append('<rect class="outline" x="%.1f" y="%.1f" width="%d" height="%d" rx="9" fill="none" stroke="none"/>' %
                      (x - 2, y - 2, CARD_W + 4, h + 4))
        hint = STATE_HINTS.get(state)
        if hint:
            parts.append("<title>%s</title>" % _esc(hint))
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="8" '
                      'fill="white" stroke="%s" stroke-width="%s"%s/>' %
                      (x, y, CARD_W, h, "#1565c0" if state == "running" else "#ddd",
                       "2.5" if state == "running" else "1.5", ' stroke-dasharray="4 3"' if state == "missing" else ""))
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="6" rx="3" fill="%s"/>' %
                      (x, y, CARD_W, type_color))
        pulse = ('<animate attributeName="opacity" values="1;0.3;1" dur="1.5s" '
                 'repeatCount="indefinite"/>') if state == "running" else ""
        parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s">%s</circle>' %
                      (x + CARD_W - 12, y + 18, state_color, pulse))
        parts.append('<text x="%.1f" y="%.1f" fill="%s" font-size="10" font-weight="bold">%s</text>' %
                      (x + 8, y + 20, type_color, _esc(job_label(job, tree.get("options", {}).get(job)).upper())))
        if alias:
            parts.append('<text x="%.1f" y="%.1f" fill="#888" font-size="10" text-anchor="end">%s</text>' %
                          (x + CARD_W - 24, y + 20, _esc(jid)))
        shown = alias or jid
        parts.append('<text x="%.1f" y="%.1f" fill="#222" font-weight="bold">%s<title>%s</title></text>' %
                      (x + 8, y + 35, _esc(shown if len(shown) <= 26 else shown[:25] + "\u2026"), _esc(alias or job)))
        for k, (label, color) in enumerate(lay["badges"]):
            bx = x + 8 + sum(len(b[0]) * 6 + 18 for b in lay["badges"][:k])
            parts.append('<rect x="%.1f" y="%.1f" width="%d" height="14" rx="7" fill="%s"/>'
                          '<text x="%.1f" y="%.1f" fill="#fff" font-size="10" font-weight="bold">%s</text>' %
                          (bx, y + HEADER_H + 2, len(label) * 6 + 12, color, bx + 6, y + HEADER_H + 12.5, _esc(label)))

        top = lay["badge_h"] + lay["anno_h"]
        anns = tree.get("annotations", {}).get(job, [])
        ax = x + 8
        shown = 0
        for a in anns[:MAX_ANNO_PILLS]:
            label = a["label"] if len(a["label"]) <= 22 else a["label"][:21] + "\u2026"
            w = len(label) * 5.6 + 12
            if shown and ax + w > x + CARD_W - 30:   # would run past the card edge: leave it to the "+N"
                break
            parts.append('<g class="anno"><title>%s</title><rect x="%.1f" y="%.1f" width="%.1f" height="14" rx="7" fill="%s"/>'
                         '<text x="%.1f" y="%.1f" fill="#fff" font-size="10">%s</text></g>' %
                         (_esc("%s: %s%s" % (a["source"], a["label"], " \u2014 " + a["detail"] if a["detail"] else "")),
                          ax, y + HEADER_H + lay["badge_h"] + 2, w, ANNO_COLORS[a["level"]],
                          ax + 6, y + HEADER_H + lay["badge_h"] + 12.5, _esc(label)))
            ax += w + 4
            shown += 1
        if len(anns) > shown:
            parts.append('<text x="%.1f" y="%.1f" font-size="10" fill="#666">+%d</text>' %
                         (ax, y + HEADER_H + lay["badge_h"] + 12.5, len(anns) - shown))
        text_y = y + HEADER_H + top + 8
        job_thumbs = thumbs[job]
        if job_thumbs:
            cols = lay["cols"]
            size = lay["thumb_size"]
            grid_x = x + (CARD_W - lay["grid_w"]) / 2
            grid_y = y + HEADER_H + top
            for i, (num, uri) in enumerate(job_thumbs):
                col, row = i % cols, i // cols
                ix = grid_x + col * (size + GRID_GAP)
                iy = grid_y + row * (size + GRID_GAP)
                sel = tree.get("selection", {}).get(job)
                hist = tree.get("classes", {}).get(sel["parent"] if sel else job) or []
                kept = sel["flags"][num - 1] if sel and num and num <= len(sel["flags"]) else None
                share = hist[-1]["shares"][num - 1] if num and hist and num <= len(hist[-1]["shares"]) else None
                tiny = (share is not None and share < TINY_CLASS_SHARE) or kept is False
                chosen_by = tree.get("chosen", {}).get(job, {}).get(num) if num else None
                parts.append('<image x="%.1f" y="%.1f" width="%d" height="%d" '
                              'href="%s" style="image-rendering: pixelated"%s/>' %
                              (ix, iy, size, size, uri, ' opacity="0.35"' if tiny else ""))
                parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" fill="none" stroke="%s" stroke-width="%s"/>' %
                              (ix, iy, size, size, "#2e7d32" if kept or chosen_by else "#eee", 3 if kept else 2 if chosen_by else 1))
                if chosen_by:  # a Select job kept this class: green check badge on the thumbnail
                    parts.append('<circle cx="%.1f" cy="%.1f" r="7" fill="#2e7d32"><title>kept by %s</title></circle>'
                                  '<text x="%.1f" y="%.1f" fill="#fff" font-size="10" font-weight="bold" text-anchor="middle">\u2713</text>' %
                                  (ix + size - 9, iy + 9, _esc(", ".join(chosen_by)), ix + size - 9, iy + 12.5))
                if num is not None and len(job_thumbs) > 1:
                    parts.append('<text x="%.1f" y="%.1f" fill="#fff" font-size="10" '
                                  'font-weight="bold" stroke="#000" stroke-width="2" '
                                  'paint-order="stroke">C%d%s</text>' %
                                  (ix + 3, iy + 11, num, (" \u2713" if kept else " \u2717" if kept is False else "") +
                                   (" %.0f%%" % (share * 100) if share is not None else "")))
            text_y = grid_y + lay["grid_h"] + 14

        parts.append('<text x="%.1f" y="%.1f" fill="%s">[%s]</text>' %
                      (x + 8, text_y, state_color, _esc(state)))
        for li, line in enumerate(lay["label_lines"]):
            parts.append('<text x="%.1f" y="%.1f" fill="#555">%s</text>' %
                          (x + 8, text_y + 14 * (li + 1), _esc(line)))

        if lay["conv"]:
            conv_y = text_y + 14 * len(lay["label_lines"]) + 16
            parts.append(_conv_svg(x + 8, conv_y, CARD_W - 16, CONV_H - 22, lay["conv"]))

        chip_list = tree.get("chips", {}).get(job, [])
        btn_h = 0 if lay["compact"] else DETAILS_BTN_H      # a missing card has no Details strip below the chips
        for k, m in enumerate(chip_list[:MAX_CHIPS]):
            cx, cy = x + 8 + k * (CHIP_W + 4), y + h - btn_h - CHIP_H + 4
            uri = chip_thumbs.get(m)
            parts.append('<g class="mask-chip" data-job="%s"><title>%s \u2014 mask used by this job</title>'
                         '<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="4" fill="#f4f8ec" stroke="#cfe0b5"/>' %
                         (_esc(m), _esc(tree.get("alias", {}).get(m) or m), cx, cy, CHIP_W, CHIP_H - 8))
            if uri:
                parts.append('<image x="%.1f" y="%.1f" width="%d" height="%d" href="%s" style="image-rendering: pixelated"/>' %
                             (cx + 2, cy + 1, CHIP_THUMB, CHIP_THUMB, uri))
            parts.append('<text x="%.1f" y="%.1f" font-size="10" fill="#4a6b1f">%s</text></g>' %
                         (cx + CHIP_THUMB + 5, cy + 17, _esc("m" + m.split("job")[-1])))
        if len(chip_list) > MAX_CHIPS:
            parts.append('<text x="%.1f" y="%.1f" font-size="10" fill="#666">+%d</text>' %
                         (x + 8 + MAX_CHIPS * (CHIP_W + 4), y + h - btn_h - 13, len(chip_list) - MAX_CHIPS))

        if not lay["compact"]:
            # A visibly clickable "Details" strip at the bottom of every card —
            # clicking anywhere on the card already opened the detail panel,
            # but nothing on the card looked clickable, so it went unnoticed.
            btn_y = y + h - DETAILS_BTN_H
            parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="0" '
                          'fill="%s" fill-opacity="0.08"/>' % (x, btn_y, CARD_W, DETAILS_BTN_H, type_color))
            parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#eee"/>' %
                          (x, btn_y, x + CARD_W, btn_y))
            parts.append('<text x="%.1f" y="%.1f" fill="%s" font-weight="bold" '
                          'text-anchor="middle">%s &#8250;</text>' %
                          (x + CARD_W / 2, btn_y + 14, type_color,
                           "Classes &amp; details" if lay["conv"] or job in tree.get("selection", {}) else "Details"))
        parts.append('</g>')

    parts.append("</svg>")
    return "\n".join(parts)
