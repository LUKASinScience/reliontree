"""FSC curves of a refinement, from RELION's own files -- the plot a methods section and a reviewer ask for first.

* PostProcess: `postprocess.star`, block `data_fsc` (corrected / masked / unmasked / phase-randomised curves);
* Refine3D without post-processing: `run_model.star` (or the newest `run_itNNN_model.star`), block `data_model_class_1`,
  the gold-standard FSC column.

The nominal resolution is where the curve first falls below 0.143 (linear interpolation between the two neighbouring
points, in spatial frequency). RELION writes its own number into the same files (`_rlnFinalResolution` of
`postprocess.star`); this one is for reading the curve, the files stay the authority. Pure stdlib."""
import re
from pathlib import Path

THRESHOLD = 0.143
MAX_POINTS = 150
_POST = (("_rlnFourierShellCorrelationCorrected", "corrected"),
         ("_rlnFourierShellCorrelationMaskedMaps", "masked maps"),
         ("_rlnFourierShellCorrelationUnmaskedMaps", "unmasked maps"),
         ("_rlnCorrectedFourierShellCorrelationPhaseRandomizedMaskedMaps", "phase-randomised"))


def _block_loop(text, block):
    """{column: [float or None, ...]} of the first loop in `data_<block>`; {} if there is none."""
    lines = text.splitlines()
    i, n, start = 0, len(lines), None
    while i < n:
        if lines[i].strip().lower() == "data_" + block.lower():
            start = i + 1
            break
        i += 1
    if start is None:
        return {}
    i = start
    while i < n and lines[i].strip().lower() != "loop_":
        if lines[i].strip().lower().startswith("data_"):
            return {}
        i += 1
    i += 1
    cols = []
    while i < n and lines[i].lstrip().startswith("_"):
        cols.append(lines[i].split()[0])
        i += 1
    out = {c: [] for c in cols}
    while i < n:
        s = lines[i].strip()
        if not s:
            if out[cols[0]] if cols else False:
                break
            i += 1
            continue
        if s.lower().startswith(("data_", "loop_")):
            break
        parts = s.split()
        if len(parts) >= len(cols):
            for c, v in zip(cols, parts):
                try:
                    out[c].append(float(v))
                except ValueError:
                    out[c].append(None)
        i += 1
    return out


def crossing(x, y, threshold=THRESHOLD):
    """Resolution in Angstrom where y (against spatial frequency x in 1/A) first falls below `threshold`; None if never."""
    for k in range(1, len(x)):
        if y[k - 1] is None or y[k] is None or x[k] <= 0:
            continue
        if y[k - 1] >= threshold > y[k]:
            f = (y[k - 1] - threshold) / (y[k - 1] - y[k])
            freq = x[k - 1] + f * (x[k] - x[k - 1])
            return 1.0 / freq if freq > 0 else None
    return None


def _decimate(x, ys):
    if len(x) <= MAX_POINTS:
        return x, ys
    step = len(x) / MAX_POINTS
    idx = sorted({int(i * step) for i in range(MAX_POINTS)} | {len(x) - 1})
    return [x[i] for i in idx], [[y[i] for i in idx] for y in ys]


def _clean(columns, xs, labels):
    """Drop rows where the frequency or every curve is missing; round for a small page."""
    rows = [i for i, f in enumerate(xs) if f is not None and f > 0]
    x = [round(xs[i], 5) for i in rows]
    ys = [[None if c[i] is None else round(c[i], 4) for i in rows] for c in columns]
    return x, ys


def _latest_model_star(job_dir):
    final = Path(job_dir) / "run_model.star"
    if final.is_file():
        return final
    its = sorted(Path(job_dir).glob("run_it*_model.star"))
    return its[-1] if its else None


def fsc_curves(job_dir):
    """{"source": file name, "threshold": 0.143, "resolution": A or None, "x": [1/A], "curves": [{"label", "y": [...]}]}
    or None when the job holds no FSC. `resolution` is the crossing of the corrected (PostProcess) or gold-standard curve."""
    job_dir = Path(job_dir)
    post = job_dir / "postprocess.star"
    try:
        if post.is_file():
            cols = _block_loop(post.read_text(encoding="utf-8", errors="ignore"), "fsc")
            res_inv = cols.get("_rlnResolution")
            if res_inv is None and cols.get("_rlnAngstromResolution"):
                res_inv = [1.0 / a if a else None for a in cols["_rlnAngstromResolution"]]
            found = [(label, cols[c]) for c, label in _POST if c in cols and len(cols[c]) == len(res_inv or [])]
            if res_inv and found:
                x, ys = _clean([f[1] for f in found], res_inv, [f[0] for f in found])
                main = ys[0]
                x_d, ys_d = _decimate(x, ys)
                return {"source": post.name, "threshold": THRESHOLD, "resolution": crossing(x, main),
                        "x": x_d, "curves": [{"label": f[0], "y": y} for f, y in zip(found, ys_d)]}
        model = _latest_model_star(job_dir)
        if model is not None:
            cols = _block_loop(model.read_text(encoding="utf-8", errors="ignore"), "model_class_1")
            res_inv, gs = cols.get("_rlnResolution"), cols.get("_rlnGoldStandardFsc")
            if res_inv and gs and len(gs) == len(res_inv):
                x, ys = _clean([gs], res_inv, ["gold-standard"])
                x_d, ys_d = _decimate(x, ys)
                return {"source": model.name, "threshold": THRESHOLD, "resolution": crossing(x, ys[0]),
                        "x": x_d, "curves": [{"label": "gold-standard", "y": ys_d[0]}]}
    except OSError:
        return None
    return None


def has_fsc(job_dir):
    """Cheap check (no parsing)."""
    d = Path(job_dir)
    return (d / "postprocess.star").is_file() or _latest_model_star(d) is not None
