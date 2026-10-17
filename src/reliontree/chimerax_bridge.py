"""Hand maps to ONE ChimeraX window without opening any network port.

A running ChimeraX with a listener on (reliontree's own, or `instantmap listen`) polls a private directory (~/.reliontree/chimerax, mode 0700) and opens
whatever map paths a request file names -- it never executes anything but `open <map>` / `tile`. If no such ChimeraX is
running, one is started with reliontree's own listener (chimerax_listener.py, run by `runscript`), so every later click
goes to that same window. InstantMap is not needed for this; `instantmap listen` does the same for a window you already
have open (and so does `runscript <path>` of the listener file, see `reliontree listener-path`).

How ChimeraX is started is a user setting (~/.reliontree/settings.json, mode 0600): the command, and an optional shell
snippet to run first, e.g. `module load chimerax` on a cluster. Both are executed by the shell on the machine where
reliontree runs, so the HTTP layer must only accept changes from its own page (see cli.py: token + Host check).
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path

HOME_DIR = Path.home() / ".reliontree"
QUEUE = HOME_DIR / "chimerax"
SETTINGS_FILE = HOME_DIR / "settings.json"
MAP_SUFFIXES = (".mrc", ".map", ".bild")
MAX_FILES = 40
ALIVE_SECS = 3.0        # listener touches `alive` every 0.5 s
STARTUP_GRACE = 90.0    # a ChimeraX we started counts as "coming up" this long before the next click starts another
MAX_CMD, MAX_PRELAUNCH = 500, 2000
SETTING_KEYS = ("chimerax_cmd", "prelaunch", "figure_template")
TEMPLATE_NAME = re.compile(r"[A-Za-z0-9 _.\-]{0,60}")      # a FigureStyle template name; goes into a ChimeraX command, so strict

LISTENER_SCRIPT = Path(__file__).with_name("chimerax_listener.py")   # run inside ChimeraX by `runscript`

_launched = None        # (Popen, start time) of the last ChimeraX this process started


def _secure_home():
    """~/.reliontree itself is owner-only too (its subfolders and settings.json already are); best effort."""
    try:
        HOME_DIR.chmod(0o700)
    except OSError:
        pass


# ---------------------------------------------------------------- settings
def load_settings():
    """{"chimerax_cmd": str, "prelaunch": str}; anything missing or malformed reads as ''."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: data[k].strip() if isinstance(data.get(k), str) else "" for k in SETTING_KEYS}


def save_settings(new):
    """Validate and store. Raises ValueError with a message for the page. A key that is not given keeps its stored value."""
    clean = load_settings()
    template = new.get("figure_template", clean["figure_template"])
    if not isinstance(template, str) or not TEMPLATE_NAME.fullmatch(template.strip()):
        raise ValueError("figure_template: letters, digits, space, _ . - only (max 60)")
    clean["figure_template"] = template.strip()
    for key, limit in (("chimerax_cmd", MAX_CMD), ("prelaunch", MAX_PRELAUNCH)):
        value = new.get(key, clean[key])
        if not isinstance(value, str):
            raise ValueError("%s must be text" % key)
        value = value.strip()
        if len(value) > limit:
            raise ValueError("%s is longer than %d characters" % (key, limit))
        if "\x00" in value:
            raise ValueError("%s contains a NUL character" % key)
        clean[key] = value
    if "\n" in clean["chimerax_cmd"] or "\r" in clean["chimerax_cmd"]:
        raise ValueError("the ChimeraX command must be a single line (put setup commands into 'Run first')")
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    HOME_DIR.chmod(0o700)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
    tmp.replace(SETTINGS_FILE)
    return clean


def _auto_chimerax():
    exe = shutil.which("chimerax") or shutil.which("ChimeraX")
    if exe:
        return exe
    apps = sorted(Path("/Applications").glob("ChimeraX*.app/Contents/MacOS/ChimeraX"))
    return str(apps[-1]) if apps else None


def describe():
    """What the settings page shows: stored values, what would be used if the command is empty, listener state."""
    return {"settings": load_settings(), "auto": _auto_chimerax() or "", "listener": listener_alive(),
            "starting": _starting(), "listener_script": str(LISTENER_SCRIPT)}


# ---------------------------------------------------------------- launching
def listener_alive():
    try:
        return time.time() - (QUEUE / "alive").stat().st_mtime < ALIVE_SECS
    except OSError:
        return False


def _starting():
    return _launched is not None and _launched[0].poll() is None and time.time() - _launched[1] < STARTUP_GRACE


def _shell_line(settings, tail):
    """One bash line: optional prelaunch, then ChimeraX with `tail` (already quoted)."""
    cmd = settings["chimerax_cmd"] or _auto_chimerax()
    if not cmd:
        raise ValueError("ChimeraX not found: set the command (and, on a cluster, 'Run first', e.g. module load chimerax) "
                         "in Settings")
    line = "exec %s %s" % (cmd if settings["chimerax_cmd"] else shlex.quote(cmd), tail)
    return (settings["prelaunch"] + "\n" + line) if settings["prelaunch"] else line


def style_line(style, n_files):
    """`figurestyle apply` for the maps just opened as #1.. (first = map, second = map2), or None. `style` is validated."""
    if not style or not TEMPLATE_NAME.fullmatch(style):
        return None
    line = 'figurestyle apply "%s" map #1' % style
    return line + " map2 #2" if n_files > 1 else line


def _launch_script(files, tile, style=""):
    """A .cxc that opens the maps (and tiles them) in a fresh ChimeraX; paths were validated by the caller."""
    folder = HOME_DIR / "launch"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    _secure_home()
    cutoff = time.time() - 86400
    for old in folder.glob("*.cxc"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    lines = ['runscript "%s"' % LISTENER_SCRIPT]            # own listener: later clicks reuse this window, no InstantMap needed
    lines += ['open "%s"' % f for f in files]
    if tile and len(files) > 1:
        lines.append("tile")
    extra = style_line(style, len(files))
    if extra:
        lines.append(extra)
    path = folder / ("open-%s.cxc" % uuid.uuid4().hex[:12])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def start_chimerax(files, tile=False, style=""):
    """Start ChimeraX with reliontree's listener running and the maps opened; remembers the process."""
    global _launched
    settings = load_settings()
    script = _launch_script(files, tile, style)
    script_line = _shell_line(settings, shlex.quote(str(script)))
    proc = subprocess.Popen(["bash", "-lc", script_line], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    _launched = (proc, time.time())
    return proc


def check_settings():
    """Run `<Run first> + <ChimeraX> --version` and return (ok, text). Does not open a window."""
    settings = load_settings()
    try:
        line = _shell_line(settings, "--version")
    except ValueError as exc:
        return False, str(exc)
    try:
        done = subprocess.run(["bash", "-lc", line], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, "timed out after 60 s"
    except OSError as exc:
        return False, str(exc)
    text = (done.stdout + done.stderr).strip()
    return done.returncode == 0, text[-1500:] or "(no output)"


def open_files(paths, tile=False, style=None):
    """Open `paths` (maps / .bild) in ChimeraX, optionally tiled side by side; returns a short status message.
    `style` (default: the figure_template setting) names a FigureStyle template to apply to the opened maps."""
    if style is None:
        style = load_settings()["figure_template"]
    files = []
    for path in paths:
        p = Path(path).resolve()
        if p.suffix.lower() not in MAP_SUFFIXES or not p.is_file():
            raise ValueError("not a map file: %s" % p.name)
        if any(c in str(p) for c in '"\n\r'):
            raise ValueError("unsupported character in the path of %s" % p.name)
        files.append(str(p))
    if not 1 <= len(files) <= MAX_FILES:
        raise ValueError("between 1 and %d files expected" % MAX_FILES)
    starting = _starting()
    if listener_alive() or starting:
        QUEUE.mkdir(parents=True, exist_ok=True)
        QUEUE.chmod(0o700)
        _secure_home()
        rid = uuid.uuid4().hex
        tmp = QUEUE / (".tmp-" + rid)
        tmp.write_text(json.dumps({"action": "tile" if tile and len(files) > 1 else "open", "paths": files,
                                   **({"style": style} if style else {})}))
        tmp.rename(QUEUE / ("req-" + rid))  # atomic: the listener never sees a half-written file
        return ("ChimeraX is still starting; the maps open as soon as it is ready" if starting and not listener_alive()
                else "sent to the running ChimeraX")
    start_chimerax(files, tile, style)
    return "started ChimeraX; further clicks go to that window"


def open_map(path):
    return open_files([path])
