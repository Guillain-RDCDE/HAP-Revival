#!/usr/bin/env python3
"""
What the HAP plays, what it ignores, and what must never reach its shares.

One definition of each, shared by the sync engine, the pre-flight validator,
the fixer and the audit. The sets come from docs/04-smb.md and the Forza
driver (docs/11-audio-path.md); the junk list from what FreeFileSync, Windows
and macOS leave behind, every one of which the HAP indexes as a phantom track.

Stdlib only.
"""

from __future__ import annotations

import os
import struct
import wave

#: Containers the player's indexer accepts (lossless PCM, DSD, lossy, ATRAC).
SUPPORTED_EXT = frozenset({
    ".flac", ".wav", ".aif", ".aiff", ".alac",
    ".dsf", ".dff",
    ".m4a", ".mp3", ".aac", ".wma",
    ".oma", ".aa3", ".at3",
})
#: Harmless companions the indexer ignores: artwork, booklets, cue sheets, and
#: files with no extension at all.
SIDECAR_EXT = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".pdf", ".txt", ".nfo", ".log", ".cue", ".m3u", ".m3u8",
    ".sfv", ".md5", ".lrc", "",
})
#: Loose artwork, by extension. The player only reads art embedded in tags, so a
#: file like this is a hint the artwork is to hand, not that the album has it.
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".gif")
#: Conventional names a loose front cover goes by.
COVER_NAMES = frozenset({
    "cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "front.jpg", "front.jpeg",
})
#: Temporary files copy tools leave behind mid-transfer.
JUNK_SUFFIXES = (".ffs_tmp", ".ffs_lock", ".part", ".partial", ".tmp", ".crdownload")
#: OS droppings.
JUNK_NAMES = frozenset({"thumbs.db", ".ds_store", "desktop.ini"})

#: The Forza PCM path tops out here; anything above must be downsampled first.
PCM_CEILING_HZ = 192_000
#: DSD64 is 2.8224 MHz, so a "sample rate" this high is DSD, not PCM.
DSD_THRESHOLD_HZ = 2_000_000

#: Suffixes the file-name locator treats as audio, derived from SUPPORTED_EXT.
AUDIO_SUFFIXES = tuple(sorted(SUPPORTED_EXT))


def is_junk(name: str) -> bool:
    """True for files that would pollute the library if copied."""
    low = name.lower()
    return low in JUNK_NAMES or low.startswith("._") or low.endswith(JUNK_SUFFIXES)


def classify(name: str) -> str:
    """One of ``audio`` | ``sidecar`` | ``junk`` | ``unsupported`` for a file name."""
    if is_junk(name):
        return "junk"
    ext = os.path.splitext(name.lower())[1]
    if ext in SUPPORTED_EXT:
        return "audio"
    if ext in SIDECAR_EXT:
        return "sidecar"
    return "unsupported"


def is_image(name: str) -> bool:
    return name.lower().endswith(IMAGE_EXT)


def is_audio(name: str) -> bool:
    return name.lower().endswith(AUDIO_SUFFIXES)


# ---------------------------------------------------------------- headers


def flac_streaminfo(path: str) -> tuple[int, int, int] | None:
    """(sample_rate, bits, channels) from a FLAC STREAMINFO block, or None.

    Reads only the first metadata block, which the format guarantees to be
    STREAMINFO. Layout at byte 10 of its body, big-endian:
    ``sample_rate(20) channels-1(3) bits-1(5) total_samples(36)``.
    """
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"fLaC":
                return None
            f.read(4)  # block header: 1 byte last-flag+type, 3 bytes length
            info = f.read(34)
    except OSError:
        return None
    if len(info) < 14:
        return None
    v = struct.unpack(">I", info[10:14])[0]
    sample_rate = v >> 12
    channels = ((v >> 9) & 0x7) + 1
    bits = ((v >> 4) & 0x1F) + 1
    return sample_rate, bits, channels


def wav_info(path: str) -> tuple[int, int, int] | None:
    """(sample_rate, bits, channels) from a WAV header, or None if unreadable."""
    try:
        with wave.open(path, "rb") as w:
            return w.getframerate(), w.getsampwidth() * 8, w.getnchannels()
    except (OSError, wave.Error, EOFError):
        return None


def pcm_sample_rate(path: str) -> int | None:
    """The sample rate of a FLAC or WAV file, or None for anything else."""
    ext = os.path.splitext(path.lower())[1]
    if ext == ".flac":
        info = flac_streaminfo(path)
    elif ext == ".wav":
        info = wav_info(path)
    else:
        return None
    return info[0] if info else None
