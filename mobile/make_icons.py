#!/usr/bin/env python3
"""Generate PWA icons (pure standard library, no PIL).

Draws an "ascending bars + arrow" finance glyph on a rounded gradient tile.
Kept within a maskable safe zone so it survives Android's icon masking.
"""
import struct
import zlib
import os

ACCENT = (52, 211, 153)   # emerald
ACCENT2 = (56, 189, 248)  # sky
BG_TOP = (15, 23, 42)     # slate-900
BG_BOT = (30, 41, 59)     # slate-800
WHITE = (241, 245, 249)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_alpha(x, y, size, radius):
    """Return True if pixel (x,y) is inside a rounded square of given size."""
    r = radius
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    dx = x - cx
    dy = y - cy
    return dx * dx + dy * dy <= r * r


def build(size):
    pixels = bytearray()
    radius = int(size * 0.22)
    pad = size * 0.20            # safe-zone padding for maskable icons
    inner = size - 2 * pad
    n_bars = 4
    gap = inner * 0.06
    bar_w = (inner - gap * (n_bars - 1)) / n_bars
    heights = [0.32, 0.52, 0.72, 0.95]  # ascending
    base_y = size - pad          # bars sit on this baseline

    for y in range(size):
        row = bytearray()
        for x in range(size):
            inside = rounded_alpha(x, y, size, radius)
            if not inside:
                row += bytes((0, 0, 0, 0))
                continue
            # gradient background
            t = y / size
            col = lerp(BG_TOP, BG_BOT, t)
            a = 255
            # bars
            for i in range(n_bars):
                bx0 = pad + i * (bar_w + gap)
                bx1 = bx0 + bar_w
                bh = inner * heights[i]
                by0 = base_y - bh
                if bx0 <= x < bx1 and by0 <= y <= base_y:
                    bt = i / (n_bars - 1)
                    col = lerp(ACCENT2, ACCENT, bt)
                    break
            row += bytes((col[0], col[1], col[2], a))
        pixels += b"\x00" + row  # filter type 0 per scanline

    raw = zlib.compress(bytes(pixels), 9)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        c += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return c

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "icons")
    os.makedirs(out, exist_ok=True)
    for s in (192, 512, 180):
        data = build(s)
        with open(os.path.join(out, f"icon-{s}.png"), "wb") as f:
            f.write(data)
        print(f"wrote icon-{s}.png ({len(data)} bytes)")
