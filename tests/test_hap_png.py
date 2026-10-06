"""The one PNG encoder behind the mock device's covers and the PWA icons."""

import struct
import zlib

import pytest

import hap_png


def _decode(data: bytes) -> tuple[int, int, bytes]:
    """Minimal reader: (width, height, raw scanlines) from a single-IDAT PNG."""
    assert data.startswith(hap_png.PNG_SIGNATURE)
    pos = 8
    width = height = 0
    idat = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, f"bad CRC on {tag!r}"
        if tag == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    return width, height, zlib.decompress(idat)


def test_rgb_round_trip():
    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9])  # 2x2
    png = hap_png.encode_png(2, 2, pixels, color_type=hap_png.COLOR_RGB)
    width, height, raw = _decode(png)
    assert (width, height) == (2, 2)
    # filter byte 0 before each of the two 6-byte rows
    assert raw == b"\x00" + pixels[:6] + b"\x00" + pixels[6:]
    assert hap_png.png_size(png) == (2, 2)


def test_rgba_round_trip():
    pixels = bytes(range(16))  # 2x2 RGBA
    png = hap_png.encode_png(2, 2, pixels, color_type=hap_png.COLOR_RGBA)
    assert _decode(png)[2] == b"\x00" + pixels[:8] + b"\x00" + pixels[8:]
    assert png.endswith(b"IEND\xae\x42\x60\x82"), "canonical empty IEND"


def test_pixel_count_is_checked():
    with pytest.raises(ValueError, match="pixel bytes"):
        hap_png.encode_png(2, 2, b"\x00" * 5)
    with pytest.raises(ValueError, match="colour type"):
        hap_png.encode_png(1, 1, b"\x00", color_type=0)


def test_png_size_rejects_non_png():
    with pytest.raises(ValueError):
        hap_png.png_size(b"GIF89a")


def test_lerp_rgb():
    assert hap_png.lerp_rgb((0, 0, 0), (100, 50, 10), 0.5) == (50, 25, 5)
    assert hap_png.lerp_rgb((0, 0, 0), (100, 50, 10), 0.0) == (0, 0, 0)
    assert hap_png.lerp_rgb((0, 0, 0), (100, 50, 10), 1.0) == (100, 50, 10)
