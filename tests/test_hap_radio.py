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

    def __call__(self, service, method, version, params):
        self.calls.append(
            {"service": service, "method": method, "version": version, "params": params}
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
