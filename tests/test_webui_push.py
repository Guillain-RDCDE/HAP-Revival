"""Tests for the web UI's push plumbing.

The UI stops polling every three seconds and instead long-polls `/api/events`,
which the server releases the moment the player pushes a UDP notification.
These tests drive that machinery directly — no device, no notifications, no
network beyond loopback. `PushWatcher.start()` is never called, so nothing ever
tries to subscribe.
"""

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import webui
from webui import HAPHandler, PushWatcher


# ---------- PushWatcher ----------


@pytest.fixture
def watcher():
    """A watcher with no background thread — we bump it by hand."""
    return PushWatcher("127.0.0.1")


def test_starts_inactive_with_no_events(watcher):
    assert watcher.generation == 0
    assert watcher.active is False


def test_returns_immediately_when_already_ahead(watcher):
    watcher._bump()
    started = time.monotonic()
    assert watcher.wait_for_change(since=0, timeout=5.0) == 1
    assert time.monotonic() - started < 1.0


def test_blocks_until_an_event_arrives(watcher):
    def bump_soon():
        time.sleep(0.1)
        watcher._bump()

    threading.Thread(target=bump_soon, daemon=True).start()
    started = time.monotonic()
    assert watcher.wait_for_change(since=0, timeout=5.0) == 1
    elapsed = time.monotonic() - started
    assert 0.05 < elapsed < 4.0        # released early, not by the timeout


def test_times_out_and_reports_the_current_generation(watcher):
    started = time.monotonic()
    assert watcher.wait_for_change(since=0, timeout=0.2) == 0
    assert time.monotonic() - started >= 0.2


def test_one_event_releases_every_waiter(watcher):
    """Several browser tabs long-poll at once; all must wake on one event."""
    results = []
    barrier = threading.Barrier(4)

    def waiter():
        barrier.wait()
        results.append(watcher.wait_for_change(since=0, timeout=5.0))

    threads = [threading.Thread(target=waiter, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    barrier.wait()
    time.sleep(0.1)
    watcher._bump()
    for t in threads:
        t.join(timeout=5)

    assert results == [1, 1, 1]


def test_generation_only_moves_forward(watcher):
    for _ in range(5):
        watcher._bump()
    assert watcher.generation == 5
    assert watcher.wait_for_change(since=4, timeout=1.0) == 5


# ---------- /api/events ----------


@pytest.fixture
def server():
    """A real HTTP server on an ephemeral loopback port, with a hand-driven
    watcher. `hap` is never touched: /api/events does not consult the device."""
    watcher = PushWatcher("127.0.0.1")
    HAPHandler.push = watcher
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), HAPHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, watcher
    httpd.shutdown()
    httpd.server_close()
    HAPHandler.push = None


def _get(httpd, path):
    host, port = httpd.server_address[:2]
    with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def test_events_releases_on_a_push(server, monkeypatch):
    httpd, watcher = server
    monkeypatch.setattr(webui, "EVENT_POLL_TIMEOUT", 5.0)

    def bump_soon():
        time.sleep(0.2)
        watcher._bump()

    threading.Thread(target=bump_soon, daemon=True).start()
    payload = _get(httpd, "/api/events?since=0")
    assert payload["generation"] == 1


def test_events_times_out_without_hanging_forever(server, monkeypatch):
    httpd, _ = server
    monkeypatch.setattr(webui, "EVENT_POLL_TIMEOUT", 0.3)
    started = time.monotonic()
    payload = _get(httpd, "/api/events?since=0")
    assert payload["generation"] == 0
    assert time.monotonic() - started < 5.0


def test_events_reports_push_inactive_until_a_subscription_succeeds(server, monkeypatch):
    """The browser keeps its own timer while `push` is false."""
    httpd, _ = server
    monkeypatch.setattr(webui, "EVENT_POLL_TIMEOUT", 0.2)
    assert _get(httpd, "/api/events?since=0")["push"] is False


def test_events_reports_push_active(server, monkeypatch):
    httpd, watcher = server
    monkeypatch.setattr(webui, "EVENT_POLL_TIMEOUT", 0.2)
    watcher.active = True
    assert _get(httpd, "/api/events?since=0")["push"] is True


@pytest.mark.parametrize("since", ["", "abc", "-1", "9999999999999"])
def test_events_survives_a_junk_since_parameter(server, monkeypatch, since):
    httpd, _ = server
    monkeypatch.setattr(webui, "EVENT_POLL_TIMEOUT", 0.2)
    payload = _get(httpd, f"/api/events?since={since}")
    assert "generation" in payload


def test_events_without_a_watcher_tells_the_browser_to_poll(monkeypatch):
    """--no-push, or a server started before the watcher exists."""
    HAPHandler.push = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), HAPHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        payload = _get(httpd, "/api/events?since=0")
        assert payload == {"push": False, "generation": 0}
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------- the claim the README makes ----------


def test_footer_string_is_translated_in_every_language():
    """The README says every interface speaks six languages. Hold it to that."""
    import i18n

    for code, catalog in i18n.CATALOGS.items():
        assert "web.footer.live" in catalog, f"{code} falls back to English"


def test_notify_cli_strings_are_translated_in_every_language():
    import i18n

    keys = [k for k in i18n.EN if k.startswith("notify.")]
    assert keys, "the notify.* catalog disappeared"
    for code, catalog in i18n.CATALOGS.items():
        missing = [k for k in keys if k not in catalog]
        assert not missing, f"{code} falls back to English for {missing}"


def test_the_old_polling_string_is_gone():
    """web.footer.polls said 'polls every 3s'. The UI no longer does."""
    import i18n

    for code, catalog in i18n.CATALOGS.items():
        assert "web.footer.polls" not in catalog, f"{code} still has the stale key"
