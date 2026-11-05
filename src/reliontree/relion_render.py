"""`reliontree render`: headless Chrome draws the /view3d page and writes PNGs. No display needed, so it also runs in a batch
script on a GPU node. Pure stdlib; the server and the browser are started by cli.cmd_render, the helpers live here."""
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from .relion_maps import RANK_CLASSES, card_maps, list_job_maps

RENDER_DIR = Path(".reliontree") / "renders"
_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
_MAC = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium")
_JOB_DIR = re.compile(r"[A-Za-z0-9_]+/job\d+")


def find_chrome(explicit=None):
    """Path of a headless-capable Chrome/Chromium or None."""
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    for n in _NAMES:
        if shutil.which(n):
            return shutil.which(n)
    return next((p for p in _MAC if os.access(p, os.X_OK)), None)


def default_jobs(project):
    """Jobs whose main result is a map worth a picture (final/post-processed/classes), e.g. 'Refine3D/job012'."""
    out = []
    for d in sorted(Path(project).glob("*/job[0-9]*")):
        job = "%s/%s" % (d.parent.name, d.name)
        maps = list_job_maps(d) if d.is_dir() and _JOB_DIR.fullmatch(job) else []
        if maps and maps[0]["rank"] <= RANK_CLASSES:
            out.append(job)
    return out


def job_files(project, job):
    """The map basenames the job's card chip would open (several = one tile each)."""
    chips = card_maps(list_job_maps(Path(project) / job))
    return chips[0]["files"] if chips else []


def num(v):
    return ("%g" % v).replace("-", "m").replace(".", "p")


def out_name(job, files, rx, ry, size, level):
    stem = re.sub(r"\W+", "-", Path(files[0]).stem) + ("+%d" % (len(files) - 1) if len(files) > 1 else "")
    lv = "auto" if level in (None, "auto") else "L" + num(float(level))
    return "%s_%s_rx%s_ry%s_s%d_%s.png" % (job.replace("/", "_"), stem, num(rx), num(ry), size, lv)


def is_fresh(out, project, job, files):
    """Cached when the PNG is newer than every map it shows."""
    try:
        t = out.stat().st_mtime
        return all((Path(project) / job / f).stat().st_mtime <= t for f in files)
    except OSError:
        return False


def tile_shape(n):
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def view_url(base, token, job, files, rx, ry, level, mode, size_tiles=None):
    q = "t=%s&job=%s&chrome=1&rx=%s&ry=%s&render=%s" % (quote(token), quote(job), rx, ry, mode)
    if level not in (None, "auto"):
        q += "&level=%s" % level
    return base + "view3d?" + q + "".join("&f=" + quote(f) for f in files)


def chrome_cmd(chrome, url, out, w, h, soft, profile):
    cmd = [chrome, "--headless=new", "--hide-scrollbars", "--ignore-gpu-blocklist", "--enable-webgl",
           "--window-size=%d,%d" % (w, h), "--user-data-dir=" + str(profile), "--screenshot=" + str(out),
           "--virtual-time-budget=%d" % (60000 if soft else 20000), "--no-first-run", "--disable-extensions"]
    if soft:
        cmd += ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.append("--no-sandbox")      # Chrome refuses to start as root otherwise (containers)
    return cmd + [url]


def shoot(chrome, url, out, w, h, soft, timeout=300):
    """Run Chrome once; True if it wrote a PNG."""
    out = Path(out)
    out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="reliontree-chrome-") as prof:
        # own process group: on a timeout Chrome's GPU/renderer children must die with it, or they keep the profile alive
        proc = subprocess.Popen(chrome_cmd(chrome, url, out, w, h, soft, prof), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=(os.name == "posix"))
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, 9) if os.name == "posix" else proc.kill()
            except OSError:
                pass
            proc.wait()
            return False
    return out.is_file() and out.stat().st_size > 0
