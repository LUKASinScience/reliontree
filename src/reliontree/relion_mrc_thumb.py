"""Cheapest-possible MRC volume preview: read the header, take the middle
Z-slice, normalize to 8-bit grayscale, and encode as a PNG data URI. Pure
stdlib (struct + zlib + array) — no numpy, no Pillow. Only mode 2 (float32)
is supported, which covers RELION's own map output (its float32-only
convention is a RELION-side guarantee, not a limitation worth relaxing
here); anything else is skipped (returns None) rather than guessed at.

Two perf tricks on top of the naive "read the whole slice" version, both
staying inside the stdlib/no-numpy constraint:
  - only the rows actually needed for the downsampled thumbnail are read
    off disk at all (one seek + read per output row instead of the whole
    Z-slice), and `array.array` (a C-level bulk unpack) replaces
    element-by-element `struct.unpack` for those rows.
  - a disk cache keyed on (path, mtime, size, thumbnail size) so a repeat
    render (e.g. every `watch`-mode auto-refresh) skips re-reading/
    re-encoding maps that haven't changed at all.
"""

import array
import base64
import sys
import hashlib
import os
import struct
import tempfile
import zlib
from pathlib import Path

_HEADER = struct.Struct("<3i i")  # nx, ny, nz, mode

_CACHE_DIR = Path(os.environ.get("RELIONTREE_CACHE_DIR") or
                   (Path(tempfile.gettempdir()) / "reliontree-thumb-cache"))


def _read_header(f):
    nx, ny, nz, mode = _HEADER.unpack(f.read(16))
    return nx, ny, nz, mode


def _cache_path(path, stat, size):
    key = "%s:%d:%d:%d" % (path, stat.st_mtime_ns, stat.st_size, size)
    return _CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".b64")


def _png_bytes(pixels, w, h):
    """8-bit grayscale PNG from a flat row-major `pixels` bytes object."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data)))

    raw = bytearray()
    for y in range(h):
        raw.append(0)  # no filter
        raw += pixels[y * w:(y + 1) * w]
    ihdr = struct.pack(">2I5B", w, h, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def mrc_slice_thumbnail(path, size=160):
    """Return a `data:image/png;base64,...` URI for the middle Z-slice of
    the MRC volume at `path`, downsampled to roughly `size` px wide, or
    None if the file is missing, too small, or not float32-mode. Cached
    on disk keyed by (path, mtime, size, thumbnail size)."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    cache_file = _cache_path(str(path), stat, size)
    try:
        return "data:image/png;base64," + cache_file.read_text()
    except OSError:
        pass

    uri = _render_thumbnail(path, size)
    if uri is not None:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(uri.split(",", 1)[1])
        except OSError:
            pass  # cache is a pure speedup; a write failure isn't fatal
    return uri


def _render_thumbnail(path, size):
    try:
        with open(path, "rb") as f:
            nx, ny, nz, mode = _read_header(f)
            if mode != 2 or nx <= 0 or ny <= 0 or nz <= 0:
                return None
            step = max(1, nx // size)
            out_w = len(range(0, nx, step))
            out_h_rows = list(range(0, ny, step))
            # skip header + any extended header would need NSYMBT, but
            # RELION maps normally carry none; best-effort.
            slice_index = nz // 2
            slice_base = 1024 + slice_index * nx * ny * 4
            row_values = []
            for y in out_h_rows:
                f.seek(slice_base + y * nx * 4)
                raw = f.read(nx * 4)
                if len(raw) != nx * 4:
                    return None
                row = array.array("f")
                row.frombytes(raw)
                if sys.byteorder != "little":  # MRC is always little-endian
                    row.byteswap()
                row_values.append(row)
    except (OSError, struct.error):
        return None

    lo = min(min(row[::step]) for row in row_values)
    hi = max(max(row[::step]) for row in row_values)
    span = (hi - lo) or 1.0

    pixels = bytearray(out_w * len(row_values))
    i = 0
    for row in row_values:
        for x in range(0, nx, step):
            pixels[i] = int((row[x] - lo) / span * 255)
            i += 1

    png = _png_bytes(pixels, out_w, len(row_values))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
