"""Which 3D maps does a RELION job directory hold? Feeds the 3D buttons (card chip + detail drawer).

Any job type can leave a map behind (Refine3D, PostProcess, MaskCreate, LocalRes, Reconstruct, InitialModel, Class3D,
MultiBody, ...), so instead of a fixed list this reads the job directory: every `.mrc` / `.map` next to the job's files
(`.mrcs` stacks are not maps) is grouped and ranked. Names only, never paths: the server rebuilds the path from a
validated job id (see cli._open_3d). Pure stdlib.
"""
import re
from pathlib import Path

MAP_SUFFIXES = (".mrc", ".map")
MAX_MAP_FILES = 60          # a directory with more than this is a particle/micrograph dump, not a result
MAX_ITER_FILES = 5000       # sanity bound for the directory scan
MAX_OTHER = 12

_CLASS_IT = re.compile(r"run_it(\d+)_class(\d+)\.(?:mrc|map)", re.IGNORECASE)
_CLASS_FINAL = re.compile(r"run_class(\d+)\.(?:mrc|map)", re.IGNORECASE)
_HALF = re.compile(r"run_half([12])_class\d+_unfil\.(?:mrc|map)", re.IGNORECASE)
_HALF_IT = re.compile(r"run_it(\d+)_half([12])_class\d+\.(?:mrc|map)", re.IGNORECASE)

# lower rank = shown first and chosen for the card's own 3D chip
RANK_POST, RANK_FINAL, RANK_CLASSES, RANK_OTHER, RANK_MASK, RANK_POST_MASKED, RANK_HALF = 0, 1, 2, 3, 4, 5, 6


def _entry(label, files, rank, tile=False):
    return {"label": label, "files": files, "tile": tile and len(files) > 1, "rank": rank}


def list_job_maps(job_dir):
    """[{label, files: [basename], tile: bool, rank: int}], most important first. [] if the job holds no map."""
    try:
        names = sorted(f.name for f in Path(job_dir).iterdir() if f.is_file() and f.suffix.lower() in MAP_SUFFIXES)
    except OSError:
        return []
    # per-iteration class/half maps (run_itNNN_*) are normal in a long classification: they do not count as a "dump"
    core = [n for n in names if not _CLASS_IT.fullmatch(n) and not _HALF_IT.fullmatch(n)]
    if not names or len(core) > MAX_MAP_FILES or len(names) > MAX_ITER_FILES:
        return []

    out, used = [], set()

    def take(*matches):
        used.update(matches)
        return list(matches)

    if "postprocess.mrc" in names:
        out.append(_entry("Post-processed", take("postprocess.mrc"), RANK_POST))
    if "postprocess_masked.mrc" in names:
        out.append(_entry("Post-processed (masked)", take("postprocess_masked.mrc"), RANK_POST_MASKED))

    finals = [n for n in names if _CLASS_FINAL.fullmatch(n)]
    if finals:
        out.append(_entry("Final map" if len(finals) == 1 else "Final classes (%d)" % len(finals),
                          take(*finals), RANK_FINAL, tile=True))

    by_iter = {}
    for n in names:
        m = _CLASS_IT.fullmatch(n)
        if m:
            by_iter.setdefault(int(m.group(1)), []).append((int(m.group(2)), n))
    if by_iter:
        last = max(by_iter)
        files = [n for _, n in sorted(by_iter[last])]
        # earlier iterations stay out of the buttons: the page's class slider is the place for those
        used.update(n for group in by_iter.values() for _, n in group)
        out.append(_entry("Final map (it %d)" % last if len(files) == 1 else "All %d classes (it %d)" % (len(files), last),
                          files, RANK_FINAL if len(files) == 1 else RANK_CLASSES, tile=True))

    halves = sorted(n for n in names if _HALF.fullmatch(n))
    if halves:
        out.append(_entry("Half maps", take(*halves), RANK_HALF, tile=True))

    half_by_iter = {}
    for n in names:
        m = _HALF_IT.fullmatch(n)
        if m:
            half_by_iter.setdefault(int(m.group(1)), []).append(n)
    if half_by_iter:      # per-iteration half maps of a refinement: only the last iteration gets a button (if no final halves)
        used.update(n for group in half_by_iter.values() for n in group)
        if not halves:
            last_half = max(half_by_iter)
            out.append(_entry("Half maps (it %d)" % last_half, sorted(half_by_iter[last_half]), RANK_HALF, tile=True))

    masks = [n for n in names if "mask" in n.lower() and n not in used]
    for n in masks:
        out.append(_entry("Mask" if len(masks) == 1 else "Mask: " + Path(n).stem, take(n), RANK_MASK))

    others = [n for n in names if n not in used]
    for n in others[:MAX_OTHER]:
        out.append(_entry(Path(n).stem, [n], RANK_OTHER))

    return sorted(out, key=lambda e: e["rank"])


def card_maps(maps):
    """What the card's own chips open: the most important entry, plus the mask if that is not the primary one."""
    if not maps:
        return []
    chips = [maps[0]]
    mask = next((m for m in maps if m["rank"] == RANK_MASK), None)
    if mask is not None and mask is not chips[0]:
        chips.append(mask)
    return chips
