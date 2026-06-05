#!/usr/bin/env python3
"""Generate the HAP-Revival PWA icon set — pure stdlib (zlib only).

Renders a warm "vinyl record" app icon at the sizes iOS / Android / Chrome
want for an installable web app, plus a maskable variant (extra safe-zone
padding so Android's adaptive mask never clips the disc).

Run once; the PNGs are committed under tools/pwa/ and served by webui.py.

    python tools/make_pwa_icons.py

Why hand-roll PNGs instead of using Pillow: the whole repo is stdlib-only by
design (see tools/webui.py), and the icon is simple geometry (concentric
rings + a gradient field) that encodes cleanly with zlib. No build dependency.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "pwa"

# Brand palette — warm hi-fi gold on a deep charcoal field (matches the web
# UI's --custom-bg / --bg). Kept fixed so the home-screen icon is stable even
# though the live UI accent is cover-derived.
FIELD_TOP = (0x1b, 0x1f, 0x2c)
FIELD_BOTTOM = (0x0e, 0x0e, 0x10)
VINYL = (0x14, 0x14, 0x16)
GROOVE = (0x2a, 0x2c, 0x32)
LABEL_HI = (0xf0, 0xb0, 0x3c)
LABEL_LO = (0xe0, 0x7b, 0x39)
SPINDLE = (0x0e, 0x0e, 0x10)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _png(width: int, height: int, pixels: bytes) -> bytes:
    """Encode RGBA pixel bytes (len = w*h*4) into a PNG byte string."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    # Prefix each scanline with filter byte 0 (no filtering).
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride : (y + 1) * stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def render(size: int, *, maskable: bool = False) -> bytes:
    """Render the vinyl icon at `size`x`size`. maskable shrinks the disc into
    the Android adaptive-icon safe zone (inner ~80%)."""
    cx = cy = (size - 1) / 2.0
    disc_r = size * (0.36 if maskable else 0.46)
    label_r = disc_r * 0.40
    spindle_r = max(1.0, disc_r * 0.045)
    groove_period = max(2.0, disc_r * 0.052)

    px = bytearray(size * size * 4)
    for y in range(size):
        # Vertical field gradient behind the disc.
        field = _lerp(FIELD_TOP, FIELD_BOTTOM, y / (size - 1))
        for x in range(size):
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy)
            if d <= disc_r:
                if d <= spindle_r:
                    r, g, b = SPINDLE
                elif d <= label_r:
                    # Diagonal gradient label so it reads as a glossy disc.
                    t = (dx + dy) / (2 * label_r) + 0.5
                    r, g, b = _lerp(LABEL_LO, LABEL_HI, max(0.0, min(1.0, t)))
                else:
                    # Grooves: faint concentric rings across the black vinyl.
                    ring = (math.sin((d - label_r) / groove_period * math.pi * 2) + 1) / 2
                    r, g, b = _lerp(VINYL, GROOVE, ring * 0.5)
                # Soft top-left specular highlight.
                hl = max(0.0, 1.0 - math.hypot(dx + disc_r * 0.35, dy + disc_r * 0.35) / (disc_r * 1.1))
                if hl > 0:
                    r, g, b = _lerp((r, g, b), (255, 255, 255), hl * 0.12)
                a = 255
            else:
                r, g, b = field
                a = 255
            # Anti-alias the disc edge over ~1px.
            if disc_r < d <= disc_r + 1.0:
                edge = d - disc_r
                vr, vg, vb = _lerp(VINYL, field, edge)
                r, g, b = vr, vg, vb
            o = (y * size + x) * 4
            px[o], px[o + 1], px[o + 2], px[o + 3] = r, g, b, a
    return _png(size, size, bytes(px))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
        ("apple-touch-icon.png", 180, False),  # iOS home-screen icon
    ]
    for name, size, maskable in targets:
        data = render(size, maskable=maskable)
        (OUT_DIR / name).write_bytes(data)
        print(f"  {name:28} {size}x{size}  {len(data):>6} B")
    print(f"Wrote {len(targets)} icons to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
