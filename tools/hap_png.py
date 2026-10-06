#!/usr/bin/env python3
"""
A minimal PNG encoder, so the tools need no Pillow.

Two things in this repository draw pictures — the mock device's cover art and
the PWA icon set — and both are simple geometry that encodes cleanly with
``zlib``. This is the one encoder they share.

Stdlib only.
"""

from __future__ import annotations

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: PNG colour types this encoder supports, with their bytes per pixel.
COLOR_RGB = 2
COLOR_RGBA = 6
_BYTES_PER_PIXEL = {COLOR_RGB: 3, COLOR_RGBA: 4}


def png_chunk(tag: bytes, data: bytes) -> bytes:
    """One PNG chunk: length, tag, data, CRC over tag+data."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: bytes, *, color_type: int = COLOR_RGB) -> bytes:
    """Encode raw 8-bit pixel bytes (row-major, no padding) as a PNG.

    ``pixels`` must hold exactly ``width * height * bytes_per_pixel`` bytes.
    Each scanline is written with filter type 0 (none): the images here are
    small and flat enough that filtering would not buy anything.
    """
    try:
        bpp = _BYTES_PER_PIXEL[color_type]
    except KeyError:
        raise ValueError(f"unsupported colour type {color_type}") from None
    stride = width * bpp
    if len(pixels) != stride * height:
        raise ValueError(
            f"expected {stride * height} pixel bytes for {width}x{height}, got {len(pixels)}"
        )
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride : (y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + png_chunk(b"IEND", b"")
    )


def png_size(data: bytes) -> tuple[int, int]:
    """(width, height) read back from a PNG's IHDR. Raises ValueError otherwise."""
    if not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


def lerp_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Linear interpolation between two RGB triples, ``t`` in 0..1."""
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )
