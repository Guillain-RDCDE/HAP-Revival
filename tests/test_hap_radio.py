"""Tests for TuneIn radio support in hap_client.

All offline: `HAP.call` is replaced with a recorder, so these assert the exact
request shapes we send and the guard rails around them. No device, no network.

The shapes come from an HTML remote contributed via Amos on 2026-08-21 and from
live probing of a Z1ES on 19404R the same day.
"""

import pytest

from hap_client import HAP


class Recorder:
    """Stands in for HAP.call, recording arguments and replaying a canned reply.

    **The reply must be shaped the way `HAP.call` returns**, i.e. already
    unwrapped from its single-element `result` list — a bare `{"isRegistered":
    false}`, not `{"result": [{...}]}`. An earlier version of this file used the
    wrapped shape, which made every test agree with a client that read nothing
    at all on a real device.
    """

    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply if reply is not None else {}

    def __call__(self, service, method, version, params=None, *, send_client_id=True):
        self.calls.append(
            {"service": service, "method": method, "version": version,
             "params": params, "send_client_id": send_client_id}
        )
        return self.reply

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def hap():
    return HAP("192.0.2.1")


# ---------- registration ----------


def test_check_sends_the_confirmed_shape(hap, monkeypatch):
    rec = Recorder({"isRegistered": False})
    monkeypatch.setattr(hap, "call", rec)
    hap.radio_registration("check")
    assert rec.last["service"] == "avContent"
    assert rec.last["method"] == "registerDevice"
    assert rec.last["version"] == "1.0"
    assert rec.last["params"] == [
        {"uri": "netService:audio?serviceName=tunein", "method": "check"}
    ]


def test_getpin_is_accepted(hap, monkeypatch):
    """Reply shape captured verbatim from a Z1ES on 19404R, 2026-08-21."""
    rec = Recorder({"pinCode": "SW94LN"})
    monkeypatch.setattr(hap, "call", rec)
    assert hap.radio_registration("getPin")["pinCode"] == "SW94LN"
    assert rec.last["params"][0]["method"] == "getPin"


def test_unknown_registration_method_is_refused_locally(hap, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    with pytest.raises(ValueError):
        hap.radio_registration("please-register-me")
    assert rec.calls == []          # never reached the device


@pytest.mark.parametrize(
    "reply,expected",
    [
        # what call() actually hands back, unwrapped — the real contract
        ({"isRegistered": True}, True),
        ({"isRegistered": False}, False),
        ({}, False),                                      # key absent
        # tolerated variants, in case the device ever surprises us
        ({"result": [{"isRegistered": True}]}, True),      # still wrapped
        ({"results": [{"isRegistered": True}]}, True),     # plural spelling
        ([{"isRegistered": True}], True),                  # bare list
        ({"result": []}, False),                           # empty
        (None, False),                                     # nothing at all
        ("not a dict", False),                             # junk
        ({"result": ["not a dict"]}, False),
    ],
)
def test_is_registered_reads_every_reply_shape(hap, monkeypatch, reply, expected):
    monkeypatch.setattr(hap, "call", Recorder(reply))
    assert hap.radio_is_registered() is expected


def test_unregistered_is_the_safe_default(hap, monkeypatch):
    """Guessing 'registered' would clear the user's playback for nothing, so
    every shape we cannot read must come back False."""
    for junk in ({}, None, "", [], {"result": [123]}):
        monkeypatch.setattr(hap, "call", Recorder(junk))
        assert hap.radio_is_registered() is False, junk


# ---------- station playback ----------


def test_play_station_sends_the_contributed_shape(hap, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    hap.play_station("s13606", "1/1/1")

    assert rec.last["method"] == "createPlayingListAndQuickPlay"
    assert rec.last["version"] == "1.0"
    params = rec.last["params"][0]
    assert params["uri"] == "netService:audio?serviceName=tunein&path=1/1/1&id=s13606"
    assert params["playbackControlMode"] == "station"
    assert params["listCount"] == 0
    assert params["listIndex"] == 0


def test_station_mode_differs_from_track_playback(hap, monkeypatch):
    """Same method, two modes — the distinction is the whole finding."""
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    hap.play_track(163756)
    hap.play_station("s13606")
    track, station = rec.calls[0]["params"][0], rec.calls[1]["params"][0]

    assert track["playbackControlMode"] == "folder"
    assert station["playbackControlMode"] == "station"
    assert track["listCount"] == 1
    assert station["listCount"] == 0
    assert track["uri"].startswith("audio:track?")
    assert station["uri"].startswith("netService:audio?")


def test_default_path_is_applied(hap, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    hap.play_station("s20291")
    assert "&path=1/1/1&" in rec.last["params"][0]["uri"]


def test_path_is_passed_through_verbatim(hap, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    hap.play_station("s308828", "1/1/3")
    assert rec.last["params"][0]["uri"].endswith("&path=1/1/3&id=s308828")


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_station_id_is_refused_locally(hap, monkeypatch, bad):
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    with pytest.raises(ValueError):
        hap.play_station(bad)
    assert rec.calls == []


def test_station_ids_are_not_coerced_to_int(hap, monkeypatch):
    """TuneIn ids carry a leading 's' — stripping it would break every call."""
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    hap.play_station("s13606")
    assert "id=s13606" in rec.last["params"][0]["uri"]

# ---------- verification, not gating ----------
#
# An earlier version refused to play on an "unregistered" player. That was
# wrong: an owner who used TuneIn while Sony supported it reports stations play
# with no account, and registration only ever synced favourites to the cloud.
# The client now attempts and reports what actually happened instead.


def test_play_station_does_not_consult_registration(hap, monkeypatch):
    """Regression guard: playback must not be gated on account state."""
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    hap.play_station("s13606")
    methods = [c["method"] for c in rec.calls]
    assert "registerDevice" not in methods
    assert methods == ["createPlayingListAndQuickPlay"]


def test_verify_false_returns_the_raw_reply(hap, monkeypatch):
    monkeypatch.setattr(hap, "call", Recorder({"uri": "audio:playinglist?id=1"}))
    result = hap.play_station("s13606")
    assert "started" not in result


def test_verify_reports_started_when_something_plays(hap, monkeypatch):
    monkeypatch.setattr(hap, "call", Recorder({"uri": "audio:playinglist?id=1"}))
    monkeypatch.setattr(hap, "_playback_started", lambda settle_sec=8.0: True)
    assert hap.play_station("s13606", verify=True)["started"] is True


def test_verify_reports_not_started_on_the_silent_failure(hap, monkeypatch):
    """The device says success while doing nothing. That is the case to catch."""
    monkeypatch.setattr(hap, "call", Recorder({"uri": "audio:playinglist?id=1"}))
    monkeypatch.setattr(hap, "_playback_started", lambda settle_sec=8.0: False)
    result = hap.play_station("s13606", verify=True)
    assert result["started"] is False
    assert result["uri"] == "audio:playinglist?id=1"      # raw reply preserved


@pytest.mark.parametrize(
    "state,title,uri,expected",
    [
        ("PLAYING", "Radio Paradise", "", True),
        ("PLAYING", "", "netService:audio?x", True),
        ("PLAYING", "", "", False),        # playing nothing at all
        ("PAUSED", "Something", "", False),
        ("STOPPED", "", "", False),
        ("", "", "", False),
    ],
)
def test_playback_started_reads_real_state(hap, monkeypatch, state, title, uri, expected):
    class FakeNP:
        pass

    np = FakeNP()
    np.state, np.title, np.uri = state, title, uri
    monkeypatch.setattr(hap, "now_playing", lambda: np)
    assert hap._playback_started(settle_sec=0) is expected


def test_playback_started_is_false_when_the_device_errors(hap, monkeypatch):
    from hap_client import HAPError

    def boom():
        raise HAPError("unreachable")

    monkeypatch.setattr(hap, "now_playing", boom)
    assert hap._playback_started(settle_sec=0) is False


# ---------- browsing: the way radio actually works ----------
#
# Everything above about registration, caches and opaque paths was wrong. A
# `path` is a position in *this player's* TuneIn tree, locale-specific, and it
# must match the station id. Browse, then play the uri you were handed.


def test_radio_browse_sends_the_working_shape(hap, monkeypatch):
    rec = Recorder([[{"title": "x"}]])
    monkeypatch.setattr(hap, "call", rec)
    hap.radio_browse("/1/1")
    assert rec.last["method"] == "getContentList"
    assert rec.last["version"] == "1.3"
    assert rec.last["params"] == [
        {"finish": False, "uri": "netService:audio?serviceName=tunein&path=/1/1"}
    ]


def test_radio_browse_omits_the_client_id_header(hap, monkeypatch):
    """x-hap-device-id makes this exact call fail with [1, "Any"] on a real
    device. Regression guard for a header that cost days."""
    seen = {}

    def spy(service, method, version, params=None, *, send_client_id=True):
        seen["send_client_id"] = send_client_id
        return [[]]

    monkeypatch.setattr(hap, "call", spy)
    hap.radio_browse("/")
    assert seen["send_client_id"] is False


def test_radio_browse_unwraps_the_double_list(hap, monkeypatch):
    """The device returns result[0] as a list of items, not the items."""
    monkeypatch.setattr(hap, "call", Recorder([[{"title": "a"}, {"title": "b"}]]))
    assert [i["title"] for i in hap.radio_browse("/")] == ["a", "b"]


def test_radio_browse_tolerates_a_flat_list(hap, monkeypatch):
    monkeypatch.setattr(hap, "call", Recorder([{"title": "a"}]))
    assert hap.radio_browse("/") == [{"title": "a"}]


def test_radio_browse_scope_is_passed_through(hap, monkeypatch):
    rec = Recorder([[]])
    monkeypatch.setattr(hap, "call", rec)
    hap.radio_browse("/", scope="favorite")
    assert rec.last["params"][0]["scope"] == "favorite"


def test_play_station_uri_sends_the_uri_verbatim(hap, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    uri = "netService:audio?serviceName=tunein&path=/1/1/3&id=s25841"
    hap.play_station_uri(uri)
    assert rec.last["method"] == "createPlayingListAndQuickPlay"
    assert rec.last["params"][0]["uri"] == uri
    assert rec.last["params"][0]["playbackControlMode"] == "station"


@pytest.mark.parametrize("bad", ["audio:track?id=1", "", "http://x", "s13606"])
def test_play_station_uri_refuses_a_non_netservice_uri(hap, monkeypatch, bad):
    rec = Recorder()
    monkeypatch.setattr(hap, "call", rec)
    with pytest.raises(ValueError):
        hap.play_station_uri(bad)
    assert rec.calls == []


# ---------- the shell that rewrote our argument ----------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("/", "/"),
        ("/1/1", "/1/1"),
        ("root", "/"),
        ("", "/"),
        ("1/1", "/1/1"),                                   # missing leading slash
        ("C:/Program Files/Git/", "/"),                    # Git Bash mangling
        (r"C:\Program Files\Git" + "\\", "/"),
        ("D:/anything", "/"),
    ],
)
def test_shell_mangled_paths_are_repaired(given, expected):
    from hap_client import _sane_tree_path

    assert _sane_tree_path(given) == expected
