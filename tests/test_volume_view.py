"""relion_volume cube + /volume and /view3d routes: synthetic maps only, validated names, token required."""
import array
import gzip
import json
import struct
import threading
import urllib.error
import urllib.request

import pytest

from reliontree import cli, relion_volume


def _write_mrc(path, n=20, cell=None):
    head = bytearray(1024)
    struct.pack_into("<4i", head, 0, n, n, n, 2)
    struct.pack_into("<3i", head, 28, n, n, n)
    struct.pack_into("<3f", head, 40, *(cell or (n * 1.5,) * 3))
    vals = array.array("f", (float(x + y + z) for z in range(n) for y in range(n) for x in range(n)))
    path.write_bytes(bytes(head) + vals.tobytes())


def test_cube_header_and_values(tmp_path, monkeypatch):
    monkeypatch.setattr(relion_volume, "_CACHE_DIR", tmp_path / "cache")
    _write_mrc(tmp_path / "m.mrc", 20)
    b = relion_volume.volume_payload(tmp_path / "m.mrc", 10)         # stride 2 -> 10^3
    nx, ny, nz, _, lo, hi, apix = relion_volume.HEADER.unpack(b[:20])
    assert (nx, ny, nz) == (10, 10, 10) and len(b) == 20 + 1000
    assert lo == 0.0 and hi == 2 * 18 + 18 and abs(apix - 3.0) < 1e-6   # largest sampled sum is 18+18+18
    cube = b[20:]
    assert cube[0] == 0 and cube[-1] == 255 and cube[1] < cube[2]      # x runs fastest, values rise with x
    assert relion_volume.volume_payload(tmp_path / "m.mrc", 10) == b   # second call is the cached one


def test_rejects_non_float32_and_flat(tmp_path, monkeypatch):
    monkeypatch.setattr(relion_volume, "_CACHE_DIR", tmp_path / "cache")
    (tmp_path / "x.mrc").write_bytes(b"\0" * 1100)
    assert relion_volume.volume_payload(tmp_path / "x.mrc") is None
    assert relion_volume.volume_payload(tmp_path / "missing.mrc") is None


def test_volume_helper_validates(tmp_path, monkeypatch):
    monkeypatch.setattr(relion_volume, "_CACHE_DIR", tmp_path / "cache")
    job = tmp_path / "proj" / "Refine3D" / "job001"
    job.mkdir(parents=True)
    _write_mrc(job / "run_class001.mrc", 12)
    proj = tmp_path / "proj"
    ok = cli._volume({"job": ["Refine3D/job001"], "f": ["run_class001.mrc"], "detail": ["32"]}, proj)
    assert gzip.decompress(ok)[:2] == struct.pack("<H", 12)
    for q in ({"job": ["../../etc"], "f": ["run_class001.mrc"]},
              {"job": ["Refine3D/job001"], "f": ["../x.mrc"]},
              {"job": ["Refine3D/job001"], "f": ["nope.mrc"]},
              {"job": ["Refine3D/job001"], "f": ["a.bild"]},
              {"job": ["Refine3D/job001"], "f": ["run_class001.mrc"], "detail": ["x"]},
              {"job": ["Refine3D/job001"]}):
        with pytest.raises(ValueError):
            cli._volume(q, proj)


def test_page_escapes_values():
    from reliontree.view3d_page import render_view3d
    page = render_view3d("Class3D/job001", ["a</script>.mrc"], "tok")
    assert "</script>.mrc" not in page and "\\u003c/script>.mrc" in page


def test_flat_map_gives_an_empty_cube(tmp_path, monkeypatch):
    monkeypatch.setattr(relion_volume, "_CACHE_DIR", tmp_path / "cache")
    head = bytearray(1024); head[:16] = struct.pack("<4i", 4, 4, 4, 2); head[28:40] = struct.pack("<3i", 4, 4, 4); head[40:52] = struct.pack("<3f", 4, 4, 4)
    (tmp_path / "flat.mrc").write_bytes(bytes(head) + struct.pack("<f", 0.5) * 64)
    p = relion_volume.volume_payload(tmp_path / "flat.mrc")
    assert p is not None and set(p[relion_volume.HEADER.size:]) == {0}
