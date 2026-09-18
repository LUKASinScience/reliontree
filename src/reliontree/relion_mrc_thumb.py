"""Cheapest-possible MRC volume preview: read the header, take the middle
Z-slice, normalize to 8-bit grayscale, and encode as a PNG data URI. Pure
stdlib (struct + zlib) — no numpy, no Pillow. Only mode 2 (float32) is
supported, which covers RELION's own map output; anything else is skipped
(returns None) rather than guessed at."""

import base64
import struct
import zlib

_HEADER = struct.Struct("<3i i")  # nx, ny, nz, mode


def _read_header(f):
    nx, ny, nz, mode = _HEADER.unpack(f.read(16))
    return nx, ny, nz, mode


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
    None if the file is missing, too small, or not float32-mode."""
    try:
        with open(path, "rb") as f:
            nx, ny, nz, mode = _read_header(f)
            if mode != 2 or nx <= 0 or ny <= 0 or nz <= 0:
                return None
            f.seek(1024)  # skip header + any extended header would need
            # NSYMBT, but RELION maps normally carry none; best-effort.
            slice_index = nz // 2
            f.seek(1024 + slice_index * nx * ny * 4)
            raw = f.read(nx * ny * 4)
            if len(raw) != nx * ny * 4:
                return None
            values = struct.unpack("<%df" % (nx * ny), raw)
    except (OSError, struct.error):
        return None

    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0

    step = max(1, nx // size)
    out_w = len(range(0, nx, step))
    out_h = len(range(0, ny, step))
    pixels = bytearray(out_w * out_h)
    i = 0
    for y in range(0, ny, step):
        row_base = y * nx
        for x in range(0, nx, step):
            v = values[row_base + x]
            pixels[i] = int((v - lo) / span * 255)
            i += 1

    png = _png_bytes(pixels, out_w, out_h)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
