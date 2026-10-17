#!/usr/bin/env python3
"""cs2relion: CryoSPARC particles -> a RELION particle STAR file that is checked before RELION sees it.

The conversion itself is done by pyem's `csparc2star.py` (Daniel Asarnow, GPL-3.0), which is called as an EXTERNAL
program: nothing of it is copied or imported here. What this script adds is the part the existing wrappers skip:

  convert   run csparc2star (with --inverty by default: CryoSPARC and RELION disagree on the y axis), then validate
  validate  check a STAR file: optics table, pixel size, image names (N@stack.mrcs), stacks on disk, optics group ids
  fix-ext   make RELION-readable `.mrcs` names: symlink name.mrc -> name.mrcs and rewrite ONLY the _rlnImageName column
            (a global sed also hits `.mrcs` -> `.mrcss` and the micrograph names); the original is kept as <file>.orig

    cs2relion.py convert --particles J5_particles.cs --passthrough J5_passthrough_particles.cs --out particles.star
    cs2relion.py validate particles.star --project /path/to/relion_project
    cs2relion.py fix-ext particles.star --project /path/to/relion_project

Exit codes: 0 ok, 1 findings of level "error", 2 usage / tool problem. What is NOT checked: that the Euler angles mean
the same in both programs (check by reconstructing and looking at the map), CTF values, and half-set assignment.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

OPTICS_REQUIRED = ("_rlnOpticsGroup", "_rlnImagePixelSize", "_rlnVoltage", "_rlnSphericalAberration", "_rlnAmplitudeContrast")
IMAGE_NAME = re.compile(r"^(\d+)@(.+)$")


def read_block(path, block):
    """(columns, rows) of the first loop in data_<block>; rows are lists of strings. ([], []) if the block is absent."""
    cols, rows, inside, loop = [], [], False, False
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                if rows:
                    break
                continue
            if s.lower().startswith("data_"):
                if inside:
                    break
                inside = s.lower() == "data_" + block
                continue
            if not inside:
                continue
            if s.lower() == "loop_":
                loop = True
            elif loop and s.startswith("_"):
                cols.append(s.split()[0])
            elif loop and not s.startswith(("#", "_")):
                rows.append(s.split())
    return cols, rows


def validate(star, project=None, max_rows=None):
    """[{"level": "error"|"warn"|"info", "what": str}, ...] for a RELION 3.1+ particle STAR file."""
    out = []

    def add(level, what):
        out.append({"level": level, "what": what})

    star = Path(star)
    if not star.is_file():
        return [{"level": "error", "what": "no such file: %s" % star}]
    ocols, orows = read_block(star, "optics")
    if not ocols:
        add("error", "no data_optics block: this is a RELION 3.0 style file; RELION 3.1+ needs the optics table "
                     "(pixel size, voltage, Cs)")
        groups, pix = set(), {}
    else:
        missing = [c for c in OPTICS_REQUIRED if c not in ocols]
        if missing:
            add("error", "optics table lacks: %s" % ", ".join(missing))
        gi = ocols.index("_rlnOpticsGroup") if "_rlnOpticsGroup" in ocols else None
        pi = ocols.index("_rlnImagePixelSize") if "_rlnImagePixelSize" in ocols else None
        groups = {r[gi] for r in orows} if gi is not None else set()
        pix = {}
        for r in orows:
            if pi is not None and gi is not None:
                try:
                    pix[r[gi]] = float(r[pi])
                except ValueError:
                    add("error", "pixel size of optics group %s is not a number: %r" % (r[gi], r[pi]))
        for g, p in pix.items():
            if not 0.3 <= p <= 10.0:
                add("warn", "pixel size %.4g A of optics group %s is outside 0.3-10 A: check units" % (p, g))
        if len(set(round(p, 4) for p in pix.values())) > 1:
            add("warn", "optics groups have different pixel sizes: %s" % pix)
    pcols, prows = read_block(star, "particles")
    if not pcols:
        add("error", "no data_particles block")
        return out
    if max_rows:
        prows = prows[:max_rows]
    add("info", "%d particles, %d optics group(s)" % (len(prows), len(groups)))
    for need in ("_rlnImageName",):
        if need not in pcols:
            add("error", "particle table lacks %s" % need)
    for angle in ("_rlnAngleRot", "_rlnAngleTilt", "_rlnAnglePsi"):
        if angle not in pcols:
            add("warn", "no %s: particles carry no alignment (fine for a fresh extraction, not for refinement)" % angle)
    if "_rlnOpticsGroup" in pcols and groups:
        gi = pcols.index("_rlnOpticsGroup")
        unknown = {r[gi] for r in prows} - groups
        if unknown:
            add("error", "particles refer to optics group(s) %s that the optics table does not define" % sorted(unknown))
    elif groups and "_rlnOpticsGroup" not in pcols:
        add("error", "particle table has no _rlnOpticsGroup column")
    if "_rlnImageName" in pcols:
        ii = pcols.index("_rlnImageName")
        stacks, bad, mrcss, wrong_ext = set(), 0, 0, 0
        for r in prows:
            m = IMAGE_NAME.match(r[ii]) if len(r) > ii else None
            if not m:
                bad += 1
                continue
            stacks.add(m.group(2))
            if m.group(2).endswith(".mrcss"):
                mrcss += 1
            elif not m.group(2).endswith(".mrcs"):
                wrong_ext += 1
        if bad:
            add("error", "%d image name(s) are not of the form N@stack.mrcs" % bad)
        if mrcss:
            add("error", "%d image name(s) end in .mrcss (a global sed replaced .mrcs twice): run fix-ext on the "
                         "original or repair the names" % mrcss)
        if wrong_ext:
            add("error", "%d image name(s) do not end in .mrcs: RELION reads stacks only with that extension; "
                         "run `fix-ext`" % wrong_ext)
        if project is not None:
            miss = [s for s in sorted(stacks) if not (Path(project) / s).exists()]
            if miss:
                add("error", "%d of %d stack file(s) not found under %s, e.g. %s" % (len(miss), len(stacks), project, miss[0]))
            else:
                add("info", "all %d stack file(s) exist under %s" % (len(stacks), project))
    return out


def fix_extensions(star, project):
    """name.mrc -> name.mrcs for the stacks named in _rlnImageName: a symlink next to the original and a rewritten
    image-name column only. The original STAR is kept as <star>.orig. Returns the number of stacks linked."""
    star, project = Path(star), Path(project)
    cols, _ = read_block(star, "particles")
    if "_rlnImageName" not in cols:
        raise ValueError("no _rlnImageName column")
    idx, linked, in_particles, header_done, ncols = cols.index("_rlnImageName"), set(), False, False, len(cols)
    lines_out = []
    with open(star, encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s.lower().startswith("data_"):
                in_particles, header_done = s.lower() == "data_particles", False
            elif in_particles and s and not s.startswith(("_", "#")) and s.lower() != "loop_":
                parts = line.split()
                m = IMAGE_NAME.match(parts[idx]) if len(parts) >= ncols else None
                if m and m.group(2).endswith(".mrc") and not m.group(2).endswith(".mrcs"):
                    src_rel = m.group(2)
                    dst_rel = src_rel + "s"
                    if src_rel not in linked:
                        src, dst = project / src_rel, project / dst_rel
                        if not src.exists():
                            raise ValueError("stack not found: %s" % src)
                        if not dst.exists() and not dst.is_symlink():
                            os.symlink(src.name, dst)           # relative link: survives moving the project
                        linked.add(src_rel)
                    parts[idx] = "%s@%s" % (m.group(1), dst_rel)
                    line = " ".join(parts) + "\n"
            lines_out.append(line)
    shutil.copyfile(star, str(star) + ".orig")
    star.write_text("".join(lines_out), encoding="utf-8")
    return len(linked)


def find_csparc2star(explicit=None):
    cand = explicit or os.environ.get("CSPARC2STAR") or shutil.which("csparc2star.py")
    if not cand or not Path(cand).exists():
        raise FileNotFoundError("csparc2star.py (pyem, https://github.com/asarnow/pyem) not found: pass --csparc2star "
                                "or set CSPARC2STAR")
    return cand


def convert(particles, out, passthrough=(), inverty=True, csparc2star=None, python=sys.executable):
    """Run pyem's csparc2star.py as an external program; returns its output file path."""
    tool = find_csparc2star(csparc2star)
    cmd = [python, tool] + (["--inverty"] if inverty else []) + [str(particles)] + [str(p) for p in passthrough] + [str(out)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0 or not Path(out).is_file():
        raise RuntimeError("csparc2star failed (exit %s):\n%s" % (done.returncode, (done.stderr or done.stdout)[-1500:]))
    return Path(out)


def _print(findings, as_json):
    if as_json:
        print(json.dumps(findings, indent=2))
    else:
        for f in findings:
            print("%-5s %s" % (f["level"].upper(), f["what"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--particles", required=True)
    c.add_argument("--passthrough", action="append", default=[])
    c.add_argument("--out", required=True)
    c.add_argument("--no-inverty", action="store_true")
    c.add_argument("--csparc2star")
    c.add_argument("--project", help="RELION project directory: also check that the stacks exist there")
    c.add_argument("--json", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("star")
    v.add_argument("--project")
    v.add_argument("--json", action="store_true")
    x = sub.add_parser("fix-ext")
    x.add_argument("star")
    x.add_argument("--project", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "convert":
            convert(a.particles, a.out, a.passthrough, not a.no_inverty, a.csparc2star)
            findings = validate(a.out, a.project)
        elif a.cmd == "validate":
            findings = validate(a.star, a.project)
        else:
            n = fix_extensions(a.star, a.project)
            print("linked %d stack(s); original kept as %s.orig" % (n, a.star))
            findings = validate(a.star, a.project)
    except (OSError, ValueError, RuntimeError) as exc:
        print("cs2relion: %s" % exc, file=sys.stderr)
        return 2
    _print(findings, getattr(a, "json", False))
    return 1 if any(f["level"] == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
