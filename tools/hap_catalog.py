#!/usr/bin/env python3
"""
The on-device SQLite catalogue (``hdd_browse.db``), decoded once.

Sony's catalogue names its tables ``FTxxxx`` and its columns ``PROPxxxx``. The
ones the tools use, so nobody has to rediscover them (see docs/09-disk-layout.md):

    FT5202 artists   PROP3601 id, PROP7020 name, PROP7065 sort, PROP7221 initial
    FT000A albums    PROP3601 id, PROP7020 name, PROP7055 album artist,
                     PROP6844 year, PROP78D9 cover thumbnail (BLOB)
    FT0002 tracks    PROP3601 id, PROP7020 title, PROP304B codec, PROP3047 duration (s),
                     PROP3048 sample rate (Hz), PROP10DE bit depth, PROP304C bitrate,
                     PROP2053 track no, PROP10A3 disc no, PROP7052 artist id,
                     PROP7045 genre id, PROPB2BB album id, PROP7007 file name,
                     PROP58D3 DRM flag, PROP10DD channel count
    FT4502 genres    PROP3601 id, PROP7020 name
    FT0000 folders

Stdlib only.
"""

from __future__ import annotations

import sqlite3
import urllib.parse

#: ``PROP304B`` codec code -> name, as the front panel spells it.
CODECS: dict[int, str] = {
    49: "FLAC", 81: "MP3", 97: "AAC", 65: "ALAC",
    129: "WMA", 17: "WAV", 33: "AIFF", 0: "?",
}


def codec_name(code: object) -> str:
    """Name for a ``PROP304B`` value; unknown codes come back as ``#<code>``."""
    return CODECS.get(int(code or 0), f"#{code}")


def _decode_mixed(raw: bytes) -> str:
    # The catalogue mixes UTF-8 with the odd Latin-1 name ("Zé Roberto");
    # never let one stray byte take a whole query down.
    return raw.decode("utf-8", "replace")


def open_catalog(path: str, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open ``hdd_browse.db`` read-only, immutable, with tolerant text decoding.

    ``immutable=1`` means no ``-wal``/``-journal`` files are created, so a copy
    of the database can sit on a read-only medium. Rows come back as
    ``sqlite3.Row`` so columns are addressable by their alias.
    """
    uri = f"file:{urllib.parse.quote(path)}?immutable=1&mode=ro"
    db = sqlite3.connect(uri, uri=True, check_same_thread=check_same_thread)
    db.text_factory = _decode_mixed
    db.row_factory = sqlite3.Row
    return db
