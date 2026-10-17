"""Runs INSIDE ChimeraX (started with `runscript <this file>`): opens the maps reliontree asks for, in this one window.

It polls ~/.reliontree/chimerax for `req-*` files (JSON {"action": "open"|"tile", "paths": [...]}, or a bare path) and
runs `open <path>` per file, plus `tile` for the opened models when asked -- nothing else is ever executed. A request
must be owned by the current user, younger than five minutes, and name existing .mrc/.map/.bild files (at most 40).
This is the same protocol as `instantmap listen` of ChimeraX-InstantMap; reliontree ships its own copy so that the 3D
buttons work without InstantMap. No network port is opened.

Do not import this file as a normal module from reliontree's own code paths: it only starts listening when it is run by
ChimeraX (a global `session` exists); importing it elsewhere (tests) only defines the functions.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

QUEUE = Path.home() / ".reliontree" / "chimerax"
MAP_SUFFIXES = (".mrc", ".map", ".bild")
MAX_FILES = 40
MAX_AGE = 300.0
POLL_SECONDS = 0.5


def _mine(path):
    return not hasattr(os, "getuid") or path.stat().st_uid == os.getuid()


TEMPLATE_NAME = re.compile(r"[A-Za-z0-9 _.\-]{1,60}")


def style_command(style, ids):
    """`figurestyle apply "<style>" map #a [map2 #b]` for the opened model ids, or None if the name is not a plain
    template name. The first map is the template's map, the second its map2 (mask / half map)."""
    if not isinstance(style, str) or not TEMPLATE_NAME.fullmatch(style) or not ids:
        return None
    cmd = 'figurestyle apply "%s" map #%s' % (style, ids[0])
    return cmd + " map2 #%s" % ids[1] if len(ids) > 1 else cmd


def _open(session, paths, tile=False, style=None):
    from chimerax.core.commands import run, quote_path_if_necessary
    models = []
    for path in paths:
        models += run(session, "open %s" % quote_path_if_necessary(str(path))) or []
    ids = [m.id_string for m in models if getattr(m, "id_string", "")]
    if tile and len(ids) > 1:
        run(session, "tile #%s" % ",".join(ids))
    cmd = style_command(style, ids)
    if cmd:
        try:
            run(session, cmd)
        except Exception as exc:                   # FigureStyle not installed or template missing: the maps stay open
            session.logger.warning("reliontree: could not apply FigureStyle template (%s)" % exc)


def _parse(text):
    """-> (paths, tile, style); raises ValueError/KeyError/TypeError on junk."""
    if text.startswith("{"):
        data = json.loads(text)
        paths, tile, style = data["paths"], data.get("action") == "tile", data.get("style")
    else:
        paths, tile, style = [text], False, None
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_FILES:
        raise ValueError("bad path list")
    return [Path(p).resolve() for p in paths], tile, style


def poll_once(session, opener=_open, queue=None):
    """Handle pending requests once; returns the paths handed to `opener`."""
    queue = queue or QUEUE
    opened = []
    for f in sorted(queue.glob("req-*")):
        try:
            if time.time() - f.stat().st_mtime > MAX_AGE:
                f.unlink()
                continue
            text = f.read_text().strip() if _mine(f) else None
            f.unlink()
            paths, tile, style = _parse(text) if text else ([], False, None)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if paths and all(p.suffix.lower() in MAP_SUFFIXES and p.is_file() for p in paths):
            opener(session, paths, tile, style)
            opened += paths
    return opened


def stop(session):
    event = getattr(session, "_reliontree_listener_stop", None)
    if event is not None:
        event.set()
        session._reliontree_listener_stop = None


def start(session):
    stop(session)                                   # running this file twice must not give two listeners
    QUEUE.mkdir(parents=True, exist_ok=True)
    QUEUE.chmod(0o700)
    try:
        QUEUE.parent.chmod(0o700)                     # ~/.reliontree: owner-only as well
    except OSError:
        pass
    if not _mine(QUEUE):
        session.logger.warning("reliontree listener: %s is not owned by you, not listening" % QUEUE)
        return
    event = session._reliontree_listener_stop = threading.Event()

    def loop():
        while not event.wait(POLL_SECONDS):
            try:
                (QUEUE / "alive").touch()
                poll_once(session, opener=lambda s, ps, t, st: s.ui.thread_safe(_open, s, ps, t, st))
            except Exception as exc:               # keep listening; show the problem in the log
                session.ui.thread_safe(session.logger.warning, "reliontree listener: %s" % exc)

    threading.Thread(target=loop, daemon=True, name="reliontree-listener").start()
    session.logger.info("reliontree listener: on (maps requested by reliontree open in this window)")


if "session" in globals():                          # started with `runscript` inside ChimeraX
    start(session)                                  # noqa: F821
