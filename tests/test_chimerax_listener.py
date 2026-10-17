"""The listener script that runs inside ChimeraX: request parsing, validation, staleness (no ChimeraX needed)."""
import importlib.util
import json
import os
import time
from pathlib import Path

from reliontree import chimerax_bridge

spec = importlib.util.spec_from_file_location("chimerax_listener", chimerax_bridge.LISTENER_SCRIPT)
lis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lis)           # no global `session` here, so nothing starts listening


def _map(tmp_path):
    m = tmp_path / "a.mrc"
    m.write_bytes(b"x")
    return m


def test_open_tile_and_legacy_requests(tmp_path):
    m, q = _map(tmp_path), tmp_path / "q"
    q.mkdir()
    (q / "req-1").write_text(json.dumps({"action": "tile", "paths": [str(m), str(m)]}))
    (q / "req-2").write_text(str(m))
    seen = []
    opened = lis.poll_once(None, opener=lambda s, paths, tile, style: seen.append((len(paths), tile)), queue=q)
    assert sorted(seen) == [(1, False), (2, True)] and len(opened) == 3 and not list(q.glob("req-*"))


def test_stale_malformed_wrong_type_and_too_many_are_dropped(tmp_path):
    m, q = _map(tmp_path), tmp_path / "q"
    q.mkdir()
    old = q / "req-old"
    old.write_text(json.dumps({"action": "open", "paths": [str(m)]}))
    ago = time.time() - lis.MAX_AGE - 5
    os.utime(old, (ago, ago))
    (q / "req-bad").write_text("{nope")
    (q / "req-type").write_text(json.dumps({"action": "open", "paths": ["/etc/passwd"]}))
    (q / "req-many").write_text(json.dumps({"action": "open", "paths": [str(m)] * 50}))
    (q / "req-notpaths").write_text(json.dumps({"action": "open", "paths": "x"}))
    seen = []
    assert lis.poll_once(None, opener=lambda *a: seen.append(a), queue=q) == [] and not seen
    assert not list(q.glob("req-*"))


def test_protocol_matches_the_sender_side():
    """Sender (bridge) and receiver (this script) must agree on suffixes and limits."""
    assert lis.MAP_SUFFIXES == chimerax_bridge.MAP_SUFFIXES and lis.MAX_FILES == chimerax_bridge.MAX_FILES
    assert lis.QUEUE.name == chimerax_bridge.QUEUE.name == "chimerax"


def test_style_command_and_request_roundtrip(tmp_path):
    import json
    from reliontree import chimerax_listener as L, chimerax_bridge as B
    assert L.style_command("Mask overlay", ["1", "2"]) == 'figurestyle apply "Mask overlay" map #1 map2 #2'
    assert L.style_command("Mask overlay", ["3"]) == 'figurestyle apply "Mask overlay" map #3'
    for bad in ('x"; shell ls', "a;b", "", None, "x" * 61, "a\nb"):
        assert L.style_command(bad, ["1"]) is None
    assert L.style_command("ok", []) is None
    assert B.style_line("Mask overlay", 2) == 'figurestyle apply "Mask overlay" map #1 map2 #2'
    assert B.style_line('a"b', 1) is None
    f = tmp_path / "m.mrc"; f.write_text("x")
    q = tmp_path / "q"; q.mkdir()
    (q / "req-1").write_text(json.dumps({"action": "open", "paths": [str(f)], "style": "Mask overlay"}))
    seen = []
    L.poll_once(None, opener=lambda s, ps, t, st: seen.append((ps, t, st)), queue=q)
    assert seen and seen[0][2] == "Mask overlay"
    (q / "req-2").write_text(str(f))                       # old bare-path form still works, no style
    L.poll_once(None, opener=lambda s, ps, t, st: seen.append((ps, t, st)), queue=q)
    assert seen[1][2] is None
