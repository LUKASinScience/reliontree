#!/usr/bin/env python3
"""chx_run: run whitelisted ChopChopMF / InstantMap / FigureStyle commands in ONE throw-away headless ChimeraX.

No port is opened and no GUI starts: each call is `ChimeraX --nogui --exit --cmd "..."` as a subprocess, so it can sit
behind an AI assistant (MCP tool, shell tool) without the REST interface. Standard library only.

    chx_run.py [--chimerax PATH] [--timeout S] [--allow-dir DIR]... CMD [CMD ...]
    chx_run.py "open /data/model.pdb" "chopchop disulfides #1"          # prints one JSON object

Rules (a request that breaks one is refused before ChimeraX starts):
  * only the verbs open / close / chopchop / instantmap / figurestyle;
  * `open` takes a local, existing file with a structure or map extension inside an allowed directory (default: the
    current directory); no fetch from the internet, no format override;
  * every absolute path argument (project folder, save file, image path) must lie inside an allowed directory;
  * no ';' or newline inside a command, no `runscript`, `pyscript`, `shell`, `exec`, `listen`;
  * network commands (chopchop pisa, foldseek*) are refused unless --allow-network.
Commands that support `jsonFile` get one automatically; its content is returned under "results".
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_CHIMERAX = "/Applications/ChimeraX-1.11.1.app/Contents/bin/ChimeraX"
VERBS = {"open", "close", "chopchop", "instantmap", "figurestyle"}
OPEN_EXT = {".pdb", ".cif", ".mmcif", ".ent", ".mrc", ".map", ".ccp4", ".mrcs"}
JSON_COMMANDS = {"chopchop disulfides", "chopchop glycosites", "chopchop asymmetry", "chopchop interfacescores",
                 "chopchop phospho", "chopchop signalpeptide", "chopchop tmhelix", "chopchop domains",
                 "instantmap tree", "instantmap table", "instantmap methods", "figurestyle list", "figurestyle info"}
NETWORK = ("chopchop pisa", "chopchop foldseek")
BAD_WORDS = {"runscript", "pyscript", "shell", "exec", "listen", "alias", "toolshed", "remotecontrol"}


class Refused(ValueError):
    pass


def check(command, allow_dirs, allow_network=False):
    """Return the command if allowed, else raise Refused."""
    c = command.strip()
    if not c or ";" in c or "\n" in c or "\r" in c:
        raise Refused("empty command, or ';' / newline inside it")
    words = c.split()
    if words[0] not in VERBS:
        raise Refused("verb %r not allowed (allowed: %s)" % (words[0], ", ".join(sorted(VERBS))))
    if BAD_WORDS & {w.lower() for w in words}:
        raise Refused("forbidden word in command")
    if not allow_network and c.lower().startswith(NETWORK):
        raise Refused("network command; pass --allow-network to permit it")
    if words[0] == "open":
        if len(words) != 2:
            raise Refused("open takes exactly one local path (no options)")
        p = Path(words[1]).expanduser().resolve()
        if p.suffix.lower() not in OPEN_EXT or not p.is_file():
            raise Refused("open: not an existing structure/map file: %s" % words[1])
        if not any(p == d or d in p.parents for d in allow_dirs):
            raise Refused("open: %s is outside the allowed directories" % p)
        return "open %s" % p
    if "jsonfile" in c.lower():
        raise Refused("jsonFile is set by the runner")
    for w in words[1:]:                       # every absolute/home path argument must stay inside the allowed directories
        if w.startswith(("/", "~")):
            p = Path(w).expanduser().resolve()
            if not any(p == d or d in p.parents for d in allow_dirs):
                raise Refused("path %s is outside the allowed directories" % w)
    return c


def run(commands, chimerax=DEFAULT_CHIMERAX, timeout=300, allow_dirs=None, allow_network=False):
    allow_dirs = [Path(d).resolve() for d in (allow_dirs or [os.getcwd()])]
    checked = [check(c, allow_dirs, allow_network) for c in commands]
    with tempfile.TemporaryDirectory(prefix="chx_run_") as tmp:
        final, outs = [], []
        for i, c in enumerate(checked):
            if " ".join(c.split()[:2]) in JSON_COMMANDS:
                out = os.path.join(tmp, "r%d.json" % i)
                c += " jsonFile " + out
                outs.append((i, checked[i], out))
            final.append(c)
        try:
            p = subprocess.run([chimerax, "--nogui", "--exit", "--cmd", "; ".join(final)],
                               capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            rc, log = p.returncode, (p.stdout + p.stderr)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout after %ss" % timeout, "commands": checked}
        results = {}
        for i, c, out in outs:
            if os.path.exists(out):
                with open(out, encoding="utf-8") as f:
                    results[c] = json.load(f)
        failed = [c for _, c, out in outs if c not in results or results[c].get("ok") is False]
        return {"ok": rc == 0 and not failed and "Traceback" not in log, "returncode": rc, "commands": checked,
                "results": results, "no_result_for": failed, "log": log[-20000:]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("commands", nargs="+")
    ap.add_argument("--chimerax", default=os.environ.get("CHIMERAX", DEFAULT_CHIMERAX))
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--allow-dir", action="append")
    ap.add_argument("--allow-network", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = run(a.commands, a.chimerax, a.timeout, a.allow_dir, a.allow_network)
    except Refused as e:
        r = {"ok": False, "error": "refused: %s" % e}
    print(json.dumps(r, indent=2))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
