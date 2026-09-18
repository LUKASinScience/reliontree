"""Assemble a RELION job lineage (pipeline graph + per-job artifacts/stats)
into plain data, and render it as SVG -- the shared, Qt/ChimeraX-free core
behind both `relion_cli.py` (a plain terminal) and `cmd.py` (the ChimeraX
command line). Pure stdlib only."""

import re
from pathlib import Path

try:
    from .relion_pipeline import load_pipeline, build_parents, upstream, limit_hops, layers as pipeline_layers
    from .relion_artifacts import scan_job_artifacts, job_stats, parse_job_options, list_class_maps
    from .relion_tree_layout import layout_positions
    from .relion_mrc_thumb import mrc_slice_thumbnail
except ImportError:
    from relion_pipeline import load_pipeline, build_parents, upstream, limit_hops, layers as pipeline_layers
    from relion_artifacts import scan_job_artifacts, job_stats, parse_job_options, list_class_maps
    from relion_tree_layout import layout_positions
    from relion_mrc_thumb import mrc_slice_thumbnail

CARD_W = 200
HEADER_H = 40          # colored bar + type label + job id line
FOOTER_LINE_H = 14     # each of the state / stats text lines below the grid
DETAILS_BTN_H = 20     # visible "Details" button strip at the bottom of every card
PADDING_BOTTOM = 6
SINGLE_THUMB_SIZE = 120
GRID_THUMB_SIZE = 56
GRID_COLS = 3
GRID_GAP = 4
_CLASS_NUM_RE = re.compile(r"class(\d+)\.mrc$", re.IGNORECASE)
STATE_COLORS = {
    "succeeded": "#2e7d32", "failed": "#c62828", "aborted": "#e65100",
    "running": "#1565c0", "unknown": "#616161",
}
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


def _class_number(path):
    m = _CLASS_NUM_RE.search(path.name)
    return int(m.group(1)) if m else None


def _job_maps(job_dir, artifacts):
    """[(class_number_or_None, path), ...] for everything a card should show
    a thumbnail for: every per-class volume when a job has more than one
    (Class2D/Class3D-style jobs), else its single most relevant map
    (postprocessed > latest class/refine map > mask)."""
    classes = list_class_maps(job_dir)
    if len(classes) > 1:
        return [(_class_number(p), p) for p in classes]
    for key in ("postprocess_map", "latest_map", "mask"):
        path = artifacts.get(key)
        if path and path.is_file():
            return [(None, path)]
    return []


def _job_thumbnails(job_dir, artifacts):
    """[(class_number_or_None, data_uri), ...], skipping any map that
    fails to decode (unsupported MRC mode, truncated file, ...)."""
    maps = _job_maps(job_dir, artifacts)
    size = GRID_THUMB_SIZE if len(maps) > 1 else SINGLE_THUMB_SIZE
    out = []
    for num, path in maps:
        uri = mrc_slice_thumbnail(path, size=size)
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

    lyrs = pipeline_layers(None, parents)  # `selected` arg is unused by layers()

    jobs = [j for layer in lyrs for j in layer]
    artifacts, stats, options, job_dirs = {}, {}, {}, {}
    for job in jobs:
        job_dir = project_dir / job
        job_dirs[job] = job_dir
        artifacts[job] = scan_job_artifacts(job_dir)
        stats[job] = job_stats(job_dir)
        options[job] = parse_job_options(job_dir)

    return {
        "layers": lyrs, "parents": parents,
        "artifacts": artifacts, "stats": stats, "options": options,
        "job_dirs": job_dirs,
    }


def ordered_jobs(tree):
    return [j for layer in tree["layers"] for j in layer]


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _card_layout(tree, job, thumbs):
    """Precompute everything geometry-dependent for one card so the size
    used for column layout and the size actually drawn agree exactly --
    two places computing slightly different heights is what let footer
    text spill past the card border before."""
    stats = tree["stats"].get(job, {})
    label2 = []
    if stats.get("resolution_angstrom"):
        label2.append("%.1f A" % stats["resolution_angstrom"])
    if stats.get("n_particles"):
        label2.append("%s particles" % format(stats["n_particles"], ","))

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

    height = (HEADER_H + grid_h + FOOTER_LINE_H + (FOOTER_LINE_H if label2 else 0) +
              PADDING_BOTTOM + DETAILS_BTN_H)
    return {
        "label2": label2, "cols": cols, "thumb_size": thumb_size,
        "grid_w": grid_w, "grid_h": grid_h, "height": height,
    }


def render_svg(tree):
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
    jobs = ordered_jobs(tree)
    thumbs = {
        j: _job_thumbnails(tree["job_dirs"][j], tree["artifacts"].get(j, {}))
        for j in jobs
    }
    layouts = {j: _card_layout(tree, j, thumbs[j]) for j in jobs}
    card_sizes = {j: (CARD_W, layouts[j]["height"]) for j in jobs}
    pos = layout_positions(tree["layers"], card_sizes)

    def bottom(job):
        x, y = pos[job]
        return x + CARD_W / 2, y + card_sizes[job][1]

    def top(job):
        x, y = pos[job]
        return x + CARD_W / 2, y

    width = max((x + CARD_W for x, y in pos.values()), default=0) + 20
    height = max((y + card_sizes[j][1] for j, (x, y) in pos.items()), default=0) + 20

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'font-family="sans-serif" font-size="11">' % (width, height),
        '<rect width="100%" height="100%" fill="white"/>',
    ]

    for job, ps in tree["parents"].items():
        if job not in pos:
            continue
        x2, y2 = top(job)
        for parent in ps:
            if parent not in pos:
                continue
            x1, y1 = bottom(parent)
            mid_y = (y1 + y2) / 2
            parts.append(
                '<path d="M %.1f %.1f V %.1f H %.1f V %.1f" '
                'fill="none" stroke="#999" stroke-width="1.5"/>' %
                (x1, y1, mid_y, x2, y2))

    for job, (x, y) in pos.items():
        lay = layouts[job]
        h = lay["height"]
        state = tree["artifacts"].get(job, {}).get("state", "unknown")
        state_color = STATE_COLORS.get(state, STATE_COLORS["unknown"])
        type_color = JOB_TYPE_COLORS.get(job_type(job), DEFAULT_TYPE_COLOR)

        parts.append('<g id="card-%s" class="job-card" data-job="%s">' % (_esc(job), _esc(job)))
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="8" '
                      'fill="white" stroke="#ddd" stroke-width="1.5"/>' % (x, y, CARD_W, h))
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="6" rx="3" fill="%s"/>' %
                      (x, y, CARD_W, type_color))
        parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s"/>' %
                      (x + CARD_W - 12, y + 18, state_color))
        parts.append('<text x="%.1f" y="%.1f" fill="%s" font-size="9" font-weight="bold">%s</text>' %
                      (x + 8, y + 20, type_color, _esc(job_type(job).upper())))
        parts.append('<text x="%.1f" y="%.1f" fill="#222">%s</text>' %
                      (x + 8, y + 33, _esc(job.split("/", 1)[1] if "/" in job else job)))

        text_y = y + HEADER_H + 8
        job_thumbs = thumbs[job]
        if job_thumbs:
            cols = lay["cols"]
            size = lay["thumb_size"]
            grid_x = x + (CARD_W - lay["grid_w"]) / 2
            grid_y = y + HEADER_H
            for i, (num, uri) in enumerate(job_thumbs):
                col, row = i % cols, i // cols
                ix = grid_x + col * (size + GRID_GAP)
                iy = grid_y + row * (size + GRID_GAP)
                parts.append('<image x="%.1f" y="%.1f" width="%d" height="%d" '
                              'href="%s" style="image-rendering: pixelated"/>' %
                              (ix, iy, size, size, uri))
                parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" fill="none" stroke="#eee"/>' %
                              (ix, iy, size, size))
                if num is not None and len(job_thumbs) > 1:
                    parts.append('<text x="%.1f" y="%.1f" fill="#fff" font-size="9" '
                                  'font-weight="bold" stroke="#000" stroke-width="2" '
                                  'paint-order="stroke">C%d</text>' % (ix + 3, iy + 11, num))
            text_y = grid_y + lay["grid_h"] + 14

        parts.append('<text x="%.1f" y="%.1f" fill="%s">[%s]</text>' %
                      (x + 8, text_y, state_color, _esc(state)))
        if lay["label2"]:
            parts.append('<text x="%.1f" y="%.1f" fill="#555">%s</text>' %
                          (x + 8, text_y + 14, _esc(" / ".join(lay["label2"]))))

        # A visibly clickable "Details" strip at the bottom of every card —
        # clicking anywhere on the card already opened the detail panel,
        # but nothing on the card looked clickable, so it went unnoticed.
        btn_y = y + h - DETAILS_BTN_H
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="0" '
                      'fill="%s" fill-opacity="0.08"/>' % (x, btn_y, CARD_W, DETAILS_BTN_H, type_color))
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#eee"/>' %
                      (x, btn_y, x + CARD_W, btn_y))
        parts.append('<text x="%.1f" y="%.1f" fill="%s" font-weight="bold" '
                      'text-anchor="middle">Details &#8250;</text>' %
                      (x + CARD_W / 2, btn_y + 14, type_color))
        parts.append('</g>')

    parts.append("</svg>")
    return "\n".join(parts)
