"""A RELION map as a small 8-bit cube for the in-browser 3D view. Pure stdlib (struct + array + zlib-free: the server
gzips the answer). Only float32 MRC (mode 2), like relion_mrc_thumb: that is what RELION writes.

Payload: `<3HH3f` header (nx, ny, nz, reserved, lo, hi, pixel size in Angstrom of the *cube*) + nx*ny*nz bytes, x fastest.
Voxel value 0..255 maps linearly to lo..hi. The cube is a plain stride-sampled copy (no averaging), at most `max_dim`
voxels along the longest axis; only the rows that are kept are read from disk.
"""
import array
import hashlib
import os
import struct
import sys
import tempfile
from pathlib import Path

HEADER = struct.Struct("<3HH3f")
_CACHE_DIR = Path(os.environ.get("RELIONTREE_CACHE_DIR") or (Path(tempfile.gettempdir()) / "reliontree-thumb-cache"))


def _cache_file(path, stat, max_dim):
    key = "vol:%s:%d:%d:%d" % (path, stat.st_mtime_ns, stat.st_size, max_dim)
    return _CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".vol")


def volume_payload(path, max_dim=128):
    """bytes (header + cube) or None if the file is missing, not float32 MRC, or implausible. Cached on disk."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    cache = _cache_file(str(path), stat, max_dim)
    try:
        return cache.read_bytes()
    except OSError:
        pass
    payload = _build(path, max_dim)
    if payload is not None:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(payload)
        except OSError:
            pass  # the cache is only a speedup
    return payload


def _build(path, max_dim):
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
            if len(head) < 1024:
                return None
            nx, ny, nz, mode = struct.unpack("<4i", head[:16])
            if mode != 2 or min(nx, ny, nz) < 2 or max(nx, ny, nz) > 4096:
                return None
            mx = struct.unpack("<3i", head[28:40])
            cell = struct.unpack("<3f", head[40:52])
            nsymbt = struct.unpack("<i", head[92:96])[0]
            apix = cell[0] / mx[0] if mx[0] > 0 and cell[0] > 0 else 1.0
            base = 1024 + max(nsymbt, 0)
            step = -(-max(nx, ny, nz) // max_dim)
            xs = range(0, nx, step)
            rows = []
            for z in range(0, nz, step):
                for y in range(0, ny, step):
                    f.seek(base + ((z * ny + y) * nx) * 4)
                    raw = f.read(nx * 4)
                    if len(raw) != nx * 4:
                        return None
                    row = array.array("f")
                    row.frombytes(raw)
                    if sys.byteorder != "little":  # MRC is little-endian
                        row.byteswap()
                    rows.append(row[::step])
    except (OSError, struct.error):
        return None

    lo = min(min(r) for r in rows)
    hi = max(max(r) for r in rows)
    if not (hi > lo):  # flat (or NaN) map: nothing to show
        return None
    k = 255.0 / (hi - lo)
    cube = bytearray()
    for r in rows:
        cube += bytes([int((v - lo) * k) for v in r])
    cx, cy, cz = len(xs), len(range(0, ny, step)), len(range(0, nz, step))
    return HEADER.pack(cx, cy, cz, 0, lo, hi, apix * step) + bytes(cube)
