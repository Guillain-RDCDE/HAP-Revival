"""Tests for the UDP push-notification client.

Two layers:
  - unit: the NOTIFY datagram parser and the SEQ deduplicator, against captured
    bytes from a real HAP-Z1ES on firmware 19404R
  - integration: a HapNotifier bound to loopback, fed by a local sender, which
    exercises bind → receive → parse → deduplicate without hardware

Nothing here touches a device or the subscription endpoint; `open()` is never
called, so no HTTP request is ever made.
"""

import socket
import threading
import time

import pytest

import hap_notify
from hap_notify import HapNotifier, NotifyEvent, SeqTracker, parse_notify


# Captured verbatim from 192.168.1.28 on 2026-08-20, firmware 19404R.
# 263 bytes, CRLF line endings, escaped slashes in the URL exactly as sent.
REAL_DATAGRAM = (
    b"NOTIFY * HTTP/1.1\r\n"
    b"Content-Length: 112\r\n"
    b"Content-Type: application/json\r\n"
    b"SEQ: 1\r\n"
    b"X-ContentServiceHostUUID: uuid:00000000-0000-1010-8000-104FA86F4B84\r\n"
    b"\r\n"
    b'{ "event": "playingtrackChanged", "url": "http:\\/\\/192.168.1.28:60200'
    b'\\/sony\\/contentplayer\\/v100\\/playinginfo" }'
)


def _datagram(event="playingtrackChanged", seq=1, uuid="uuid:aaa", url=None):
    url_part = f', "url": "{url}"' if url else ""
    body = f'{{ "event": "{event}"{url_part} }}'
    return (
        "NOTIFY * HTTP/1.1\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Content-Type: application/json\r\n"
        f"SEQ: {seq}\r\n"
        f"X-ContentServiceHostUUID: {uuid}\r\n"
        "\r\n"
        f"{body}"
    ).encode("utf-8")


# ---------- parser ----------


def test_parses_the_real_captured_datagram():
    event = parse_notify(REAL_DATAGRAM)
    assert event is not None
    assert event.name == "playingtrackChanged"
    assert event.seq == 1
    assert event.host_uuid == "uuid:00000000-0000-1010-8000-104FA86F4B84"
    # JSON unescapes the slashes the player escapes on the wire
    assert event.url == "http://192.168.1.28:60200/sony/contentplayer/v100/playinginfo"
    assert event.body["event"] == "playingtrackChanged"


def test_readback_prefers_the_url_the_player_sent():
    event = parse_notify(REAL_DATAGRAM)
    assert event.readback_path.startswith("http://")


def test_readback_falls_back_to_the_documented_map():
    """An event with no `url` still resolves, case-insensitively."""
    event = parse_notify(_datagram(event="powerstateChanged"))
    assert event.url is None
    assert event.readback_path == "/sony/contentplayer/v100/powerstate"


def test_every_documented_event_has_a_readback_path():
    for name in (
        "playingtrackChanged",
        "playinginfoChanged",
        "playqueueChanged",
        "powerstateChanged",
        "volumeChanged",
    ):
        event = parse_notify(_datagram(event=name))
        assert event.readback_path, name


def test_unknown_event_parses_but_has_no_readback():
    event = parse_notify(_datagram(event="somethingNobodyHasSeen"))
    assert event is not None
    assert event.name == "somethingNobodyHasSeen"
    assert event.readback_path is None


def test_tolerates_bare_lf_and_lowercase_headers():
    raw = (
        b"NOTIFY * HTTP/1.1\n"
        b"seq: 7\n"
        b"content-type: application/json\n"
        b"\n"
        b'{"event": "volumeChanged"}'
    )
    event = parse_notify(raw)
    assert event is not None and event.seq == 7


def test_tolerates_a_missing_blank_line():
    raw = b'NOTIFY * HTTP/1.1\r\nSEQ: 3\r\n{"event": "playqueueChanged"}'
    event = parse_notify(raw)
    assert event is not None and event.seq == 3


def test_missing_seq_header_yields_none_not_a_crash():
    raw = b'NOTIFY * HTTP/1.1\r\n\r\n{"event": "playqueueChanged"}'
    event = parse_notify(raw)
    assert event is not None and event.seq is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00",
        b"not http at all",
        b"M-SEARCH * HTTP/1.1\r\n\r\n{}",           # SSDP, not ours
        b"NOTIFY * HTTP/1.1\r\n\r\nnot json",
        b'NOTIFY * HTTP/1.1\r\n\r\n{"no": "event key"}',
        b'NOTIFY * HTTP/1.1\r\n\r\n["a list"]',
        b"NOTIFY * HTTP/1.1\r\nSEQ: 1\r\n\r\n" + b"\xff\xfe invalid utf8",
    ],
)
def test_rejects_junk(raw):
    assert parse_notify(raw) is None


def test_non_integer_seq_is_tolerated():
    raw = b'NOTIFY * HTTP/1.1\r\nSEQ: banana\r\n\r\n{"event": "volumeChanged"}'
    event = parse_notify(raw)
    assert event is not None and event.seq is None


# ---------- deduplication ----------


def test_drops_the_two_retransmissions():
    """The player sends every event three times under one SEQ."""
    tracker = SeqTracker()
    events = [parse_notify(_datagram(seq=1)) for _ in range(3)]
    assert [tracker.is_new(e) for e in events] == [True, False, False]


def test_a_new_seq_is_a_new_event():
    tracker = SeqTracker()
    assert tracker.is_new(parse_notify(_datagram(seq=1)))
    assert tracker.is_new(parse_notify(_datagram(seq=2)))


def test_two_players_are_tracked_independently():
    """One listener can serve several HAPs; their SEQ counters are unrelated."""
    tracker = SeqTracker()
    assert tracker.is_new(parse_notify(_datagram(seq=1, uuid="uuid:one")))
    assert tracker.is_new(parse_notify(_datagram(seq=1, uuid="uuid:two")))
    assert not tracker.is_new(parse_notify(_datagram(seq=1, uuid="uuid:one")))


def test_falls_back_to_source_address_when_uuid_is_absent():
    tracker = SeqTracker()
    raw = b'NOTIFY * HTTP/1.1\r\nSEQ: 4\r\n\r\n{"event": "volumeChanged"}'
    event = parse_notify(raw)
    assert tracker.is_new(event, "10.0.0.1")
    assert not tracker.is_new(parse_notify(raw), "10.0.0.1")
    assert tracker.is_new(parse_notify(raw), "10.0.0.2")


def test_seqless_events_always_pass():
    """We would rather act twice than swallow a real change."""
    tracker = SeqTracker()
    raw = b'NOTIFY * HTTP/1.1\r\n\r\n{"event": "volumeChanged"}'
    assert tracker.is_new(parse_notify(raw))
    assert tracker.is_new(parse_notify(raw))


# ---------- notifier, over loopback ----------


@pytest.fixture
def notifier():
    """A notifier bound to an ephemeral loopback port, never subscribed."""
    n = HapNotifier("127.0.0.1", listen_port=0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    n._sock = sock
    n.listen_port = sock.getsockname()[1]
    # far in the future: events() must not try to re-arm during these tests
    n._next_rearm = time.monotonic() + 3600
    yield n
    n.close()


def test_handle_datagram_deduplicates(notifier):
    assert notifier.handle_datagram(REAL_DATAGRAM, "127.0.0.1") is not None
    assert notifier.handle_datagram(REAL_DATAGRAM, "127.0.0.1") is None


def test_handle_datagram_ignores_junk(notifier):
    assert notifier.handle_datagram(b"garbage", "127.0.0.1") is None


def test_events_yields_deduplicated_events_over_the_wire(notifier):
    """End-to-end: three retransmissions of two events arrive; two are yielded."""
    target = notifier._sock.getsockname()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send():
        time.sleep(0.05)
        for seq in (1, 1, 1, 2, 2, 2):
            sender.sendto(_datagram(seq=seq), target)

    thread = threading.Thread(target=send, daemon=True)
    thread.start()

    received = list(notifier.events(duration=2.0))
    thread.join(timeout=2)
    sender.close()

    assert [e.seq for e in received] == [1, 2]


def test_events_requires_open():
    with pytest.raises(RuntimeError):
        list(HapNotifier("127.0.0.1").events(duration=0.1))


def test_close_while_iterating_ends_cleanly(notifier):
    """A listener thread shut down by its owner must stop, not raise.

    Found by running a real capture against a Z1ES: the probe closed the
    notifier while its listener thread was still inside recvfrom, and the
    thread died with an exception instead of finishing.
    """
    collected = []
    errors = []

    def listen():
        try:
            collected.extend(notifier.events(duration=30))
        except Exception as exc:            # noqa: BLE001 — that's the point
            errors.append(exc)

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    time.sleep(0.3)
    notifier.close()
    thread.join(timeout=5)

    assert not thread.is_alive(), "events() did not return after close()"
    assert errors == [], f"close() raised instead of stopping: {errors}"


def test_rearm_failure_does_not_kill_the_loop(notifier, monkeypatch):
    """A wedged daemon costs us a re-arm, not the whole listener."""
    calls = []

    def failing_subscribe():
        calls.append(1)
        raise hap_notify.NotifyError("daemon wedged")

    monkeypatch.setattr(notifier, "subscribe", failing_subscribe)
    notifier._next_rearm = time.monotonic() - 1      # due immediately

    assert list(notifier.events(duration=1.5)) == []
    assert calls, "subscribe() was never retried"


def test_fetch_returns_none_for_an_unreachable_url(notifier):
    """A dead readback must not propagate an exception into the event loop."""
    event = parse_notify(
        _datagram(url="http://127.0.0.1:1/sony/contentplayer/v100/playinginfo")
    )
    assert notifier.fetch(event) is None


def test_fetch_returns_none_when_there_is_nothing_to_read(notifier):
    event = parse_notify(_datagram(event="unknownThing"))
    assert notifier.fetch(event) is None


# ---------- constants that encode findings ----------


def test_subscribe_path_carries_the_sony_prefix():
    """The Crestron module's own path omits it and 404s. Regression guard."""
    assert hap_notify.SUBSCRIBE_PATH == "/sony/notification/status"


def test_rearm_happens_before_the_subscription_expires():
    assert 0 < hap_notify.REARM_FRACTION < 1
