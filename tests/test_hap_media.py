"""What the HAP plays, what it ignores, and what must never reach it.

One definition shared by the sync engine, the validator, the fixer and the
audit — so these are the rules the README promises ("skips the junk", "skips
formats the HAP can't play"), pinned once.
"""

import struct
import wave

import pytest

import hap_media

# ---------- is_junk ----------


@pytest.mark.parametrize("name", [
    "Thumbs.db", "THUMBS.DB", ".DS_Store", "desktop.ini",
    "._AppleDouble", "._cover.jpg",
    "track.flac.ffs_tmp", "album.part", "x.partial", "y.tmp", "z.crdownload",
    "scan.ffs_lock",
])
def test_is_junk_true(name):
    assert hap_media.is_junk(name) is True


@pytest.mark.parametrize("name", [
    "01 - Song.flac", "cover.jpg", "folder.png", "notes.txt",
    "temple.flac",   # ends with 'le' not '._' — must not trip the AppleDouble rule
    "thumbs.dbx",    # not exactly thumbs.db
])
def test_is_junk_false(name):
    assert hap_media.is_junk(name) is False


# ---------- classify ----------


@pytest.mark.parametrize("name,kind", [
    ("a.flac", "audio"), ("a.FLAC", "audio"), ("a.dsf", "audio"), ("a.mp3", "audio"),
    ("a.m4a", "audio"), ("a.wav", "audio"), ("a.aiff", "audio"), ("a.at3", "audio"),
    ("cover.jpg", "sidecar"), ("notes.txt", "sidecar"), ("list.m3u", "sidecar"),
    ("lyrics.lrc", "sidecar"), ("art.webp", "sidecar"),
    ("README", "sidecar"),                # no extension -> sidecar bucket
    ("Thumbs.db", "junk"), ("._x.flac", "junk"), ("x.ffs_tmp", "junk"),
    ("movie.mkv", "unsupported"), ("a.ogg", "unsupported"), ("a.opus", "unsupported"),
])
def test_classify(name, kind):
    assert hap_media.classify(name) == kind


def test_junk_beats_extension():
    # An AppleDouble shadow of a real audio file is junk, not audio.
    assert hap_media.classify("._track.flac") == "junk"


def test_audio_and_image_predicates():
    assert hap_media.is_audio("x.FLAC") and hap_media.is_audio("y.aac")
    assert not hap_media.is_audio("cover.jpg")
    assert hap_media.is_image("Cover.JPG") and not hap_media.is_image("a.flac")
    assert set(hap_media.AUDIO_SUFFIXES) == hap_media.SUPPORTED_EXT


# ---------- header parsers ----------


def write_flac(path, sample_rate, bits=24, channels=2):
    """Write a minimal file with a valid FLAC STREAMINFO block for the parser.

    Only the 4-byte word at STREAMINFO offset 10 matters: it packs
    sample_rate(20) | channels-1(3) | bits-1(5) | top-4-bits-of-total-samples."""
    v = (sample_rate << 12) | ((channels - 1) << 9) | ((bits - 1) << 4) | 0
    info = b"\x00" * 10 + struct.pack(">I", v) + b"\x00" * 20  # 34-byte STREAMINFO
    block_header = b"\x00\x00\x00\x22"  # type 0 (STREAMINFO), length 0x22 = 34
    path.write_bytes(b"fLaC" + block_header + info)


def write_wav(path, sample_rate, bits=16, channels=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(bits // 8)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00" * (bits // 8) * channels)  # one frame is enough


def test_flac_streaminfo_roundtrip(tmp_path):
    p = tmp_path / "a.flac"
    write_flac(p, 96000, bits=24, channels=2)
    assert hap_media.flac_streaminfo(str(p)) == (96000, 24, 2)


def test_flac_streaminfo_dxd(tmp_path):
    p = tmp_path / "dxd.flac"
    write_flac(p, 352800, bits=24, channels=2)
    assert hap_media.flac_streaminfo(str(p))[0] == 352800


def test_flac_streaminfo_rejects_non_flac(tmp_path):
    p = tmp_path / "x.flac"
    p.write_bytes(b"NOTFLAC" + b"\x00" * 40)
    assert hap_media.flac_streaminfo(str(p)) is None


def test_flac_streaminfo_rejects_a_truncated_header(tmp_path):
    p = tmp_path / "short.flac"
    p.write_bytes(b"fLaC\x00\x00\x00\x22" + b"\x00" * 5)
    assert hap_media.flac_streaminfo(str(p)) is None
    assert hap_media.flac_streaminfo(str(tmp_path / "absent.flac")) is None


def test_wav_info_roundtrip(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, 44100, bits=16, channels=2)
    assert hap_media.wav_info(str(p)) == (44100, 16, 2)


def test_wav_info_rejects_garbage(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"not a wav")
    assert hap_media.wav_info(str(p)) is None


def test_pcm_sample_rate_dispatches_on_extension(tmp_path):
    write_flac(tmp_path / "a.flac", 192000)
    write_wav(tmp_path / "b.wav", 384000)
    (tmp_path / "c.mp3").write_bytes(b"\xff\xfb")
    assert hap_media.pcm_sample_rate(str(tmp_path / "a.flac")) == 192000
    assert hap_media.pcm_sample_rate(str(tmp_path / "b.wav")) == 384000
    assert hap_media.pcm_sample_rate(str(tmp_path / "c.mp3")) is None
    assert hap_media.pcm_sample_rate(str(tmp_path / "missing.flac")) is None
