"""The three probe scripts (call.py, discover.py, api-fuzzer.py) and the raw
JSON-RPC transport they share, driven against the mock device.

They used to carry three private copies of the same POST; now they share one,
and a shape the device answers with is interpreted the same way by all three.
"""

import importlib
import json
import threading

import pytest

import call as call_tool
import discover
import hap_client
import mock_hap

fuzzer = importlib.import_module("api-fuzzer")


@pytest.fixture
def device():
    server = mock_hap.make_server("127.0.0.1", 0, quiet=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    mock_hap.STATE = mock_hap.DeviceState()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()


# ---------- the transport ----------


def test_rpc_request_shape():
    req = hap_client.rpc_request("http://h:1/sony/system", "getPowerStatus", "1.1")
    assert req.get_method() == "POST"
    assert json.loads(req.data) == {
        "method": "getPowerStatus", "id": 1, "params": [], "version": "1.1"}
    assert req.get_header("Content-type") == "application/json"
    assert not req.has_header("X-hap-device-id"), "the header is opt-in"
    assert not req.has_header("Expect"), "100-continue makes the player answer 417"
    with_id = hap_client.rpc_request("http://h:1/sony/x", "m", "1.0", [{}], client_id="me")
    assert with_id.get_header("X-hap-device-id") == "me"


def test_rpc_post_against_the_mock(device):
    host, port = device
    reply = hap_client.rpc_post(host, "system", "getPowerStatus", "1.1", port=port, timeout=10)
    assert reply.ok and reply.status == 200
    assert reply.body["result"] == [{"status": "active", "standbyDetail": ""}]
    assert reply.as_dict()["status"] == 200 and "error" not in reply.as_dict()


def test_rpc_post_reports_the_devices_error_tuple(device):
    host, port = device
    reply = hap_client.rpc_post(host, "system", "noSuchMethod", "1.0", port=port, timeout=10)
    assert reply.status == 200 and not reply.ok
    assert reply.rpc_error == [12, "No Such Method"]


def test_rpc_post_reports_transport_failures():
    reply = hap_client.rpc_post("127.0.0.1", "system", "x", "1.0", port=1, timeout=1)
    assert reply.status == 0 and reply.error and not reply.ok
    assert reply.as_dict()["error"] == reply.error


def test_rpc_post_keeps_a_non_json_answer_and_http_errors(device):
    host, port = device
    # /sony/ with no service: the mock's dispatcher cannot route it.
    reply = hap_client.rpc_post(host, "", "x", "1.0", port=port, timeout=10)
    assert not reply.ok
    plain = hap_client.RpcReply(200, "<html>oops</html>")
    assert plain.rpc_error is None and plain.ok
    odd = hap_client.RpcReply(200, {"error": "a bare string"})
    assert odd.rpc_error == [-1, "a bare string"]


def test_hap_call_maps_replies_to_exceptions(device):
    host, port = device
    hap = hap_client.HAP(host, port=port, timeout=10)
    with pytest.raises(hap_client.HAPMethodError) as exc:
        hap.call("system", "noSuchMethod", "1.0")
    assert exc.value.code == 12 and exc.value.method == "noSuchMethod"
    with pytest.raises(hap_client.HAPTransportError):
        hap_client.HAP("127.0.0.1", port=1, timeout=1).call("system", "getPowerStatus", "1.1")
    with pytest.raises(ValueError):
        hap_client.HAP("")


def test_upnp_field_reads_plain_and_namespaced_tags():
    xml = ("<root><device><UDN>uuid:abc-123</UDN>"
           "<av:X_HAP_Version> 1.2 </av:X_HAP_Version></device></root>")
    assert hap_client.upnp_field(xml, "UDN") == "uuid:abc-123"
    assert hap_client.upnp_field(xml, "X_HAP_Version") == "1.2"
    assert hap_client.upnp_field(xml, "modelName") is None


def test_upnp_description_raises_a_transport_error_when_unreachable():
    with pytest.raises(hap_client.HAPTransportError):
        hap_client.upnp_description("127.0.0.1", port=1, timeout=1)


def test_device_uuid_short_strips_the_prefix(monkeypatch):
    hap = hap_client.HAP("1.2.3.4")
    monkeypatch.setattr(hap_client, "upnp_description", lambda ip, timeout: "<UDN>uuid:X-1</UDN>")
    assert hap._device_uuid_short() == "X-1"
    monkeypatch.setattr(hap_client, "upnp_description", lambda ip, timeout: "<root/>")
    with pytest.raises(hap_client.HAPError):
        hap._device_uuid_short()


# ---------- call.py ----------


def test_call_prints_the_reply_and_saves_a_capture(device, tmp_path, capsys, monkeypatch):
    host, port = device
    monkeypatch.setattr(call_tool, "save_capture",
                        lambda prefix, payload, tool: tmp_path / f"{prefix}.json"
                        if (tmp_path / f"{prefix}.json").write_text(json.dumps(payload)) else None)
    rc = call_tool.main(["--target", host, "--port", str(port), "--service", "system",
                         "--method", "getPowerStatus", "--version", "1.1", "--save"])
    assert rc == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["result"] == [{"status": "active", "standbyDetail": ""}]
    assert "HTTP 200" in err and "Saved:" in err
    saved = json.loads((tmp_path / "call-system-getPowerStatus-v1.1.json").read_text())
    assert saved["request"]["method"] == "getPowerStatus"
    assert saved["response"]["status"] == 200


def test_call_rejects_bad_params_json(capsys):
    rc = call_tool.main(["--target", "h", "--service", "s", "--method", "m", "--version", "1.0",
                         "--params", "{oops"])
    assert rc == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_call_fails_when_the_device_is_unreachable(capsys):
    rc = call_tool.main(["--target", "127.0.0.1", "--port", "1", "--service", "system",
                         "--method", "m", "--version", "1.0", "--timeout", "1"])
    assert rc == 1
    assert "HTTP 0" in capsys.readouterr().err


# ---------- discover.py ----------


def test_ssdp_responses_are_folded_per_device():
    hap = (b"HTTP/1.1 200 OK\r\nST: urn:schemas-upnp-org:device:MediaServer:1\r\n"
           b"SERVER: Linux UPnP/1.0 Sony-HAP/1.0\r\nLOCATION: http://1.2.3.4:60100/hap.xml\r\n\r\n")
    other = b"HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\nSERVER: Something Else\r\n\r\n"
    devices = discover.collect_ssdp([("1.2.3.4", hap), ("9.9.9.9", other),
                                     ("1.2.3.4", hap.replace(b"MediaServer", b"MediaRenderer"))])
    assert len(devices) == 1
    assert devices[0]["ip"] == "1.2.3.4"
    assert devices[0]["headers"]["location"] == "http://1.2.3.4:60100/hap.xml"
    assert devices[0]["services"] == ["urn:schemas-upnp-org:device:MediaServer:1",
                                      "urn:schemas-upnp-org:device:MediaRenderer:1"]
    assert discover.ssdp_message().startswith(b"M-SEARCH * HTTP/1.1\r\n")


def test_probe_device_records_every_known_method(device, capsys):
    host, port = device
    import hap_common

    # The mock serves hap.xml nowhere, so the UPnP step reports an error and
    # the JSON-RPC probe carries on.
    discover.jsonrpc_call.__defaults__ = (port,)
    try:
        result = discover.probe_device(host)
    finally:
        discover.jsonrpc_call.__defaults__ = (hap_common.API_PORT,)
    assert result["hap_xml"] is None
    probed = [r["method"] for r in result["api_probe"]]
    assert probed == [m for _, m, _, _ in discover.KNOWN_METHODS]
    by_method = {r["method"]: r["response"] for r in result["api_probe"]}
    assert by_method["getSystemInformation"]["body"]["result"][0]["model"] == "HAP-Z1ES"
    out = capsys.readouterr().out
    assert "[OK ] system.getSystemInformation" in out
    assert "[ERR] system.getInterfaceInformation" in out, "the mock lacks it: an honest ERR"


def test_discover_main_direct_target_saves_a_report(device, tmp_path, capsys, monkeypatch):
    host, _port = device
    monkeypatch.setattr(discover, "probe_device", lambda ip: {"ip": ip, "api_probe": []})
    monkeypatch.setattr(discover, "save_capture",
                        lambda prefix, payload, tool: tmp_path / "report.json")
    assert discover.main(["--target", host]) == 0
    assert "Report saved" in capsys.readouterr().out


def test_discover_main_without_devices_fails(monkeypatch, capsys):
    monkeypatch.setattr(discover, "ssdp_search", lambda: [])
    assert discover.main([]) == 1
    assert "No HAP devices" in capsys.readouterr().out


def test_discover_main_quick_skips_the_probe(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(discover, "ssdp_search",
                        lambda: [{"ip": "1.2.3.4", "headers": {}, "services": ["x"]}])
    monkeypatch.setattr(discover, "probe_device", lambda ip: pytest.fail("must not probe"))
    saved = {}
    monkeypatch.setattr(discover, "save_capture",
                        lambda prefix, payload, tool: saved.update(payload) or tmp_path / "r.json")
    assert discover.main(["--quick"]) == 0
    assert saved["devices"] == [{"ip": "1.2.3.4", "services": ["x"], "headers": {}}]


# ---------- api-fuzzer.py ----------


@pytest.mark.parametrize("reply,klass", [
    (hap_client.RpcReply(0, None, "refused"), "TRANSPORT"),
    (hap_client.RpcReply(500, None, "HTTP 500: boom"), "TRANSPORT"),
    (hap_client.RpcReply(200, {"result": [{}]}), "OK"),
    (hap_client.RpcReply(200, {"error": [12, "No Such Method"]}), "NO_SUCH_METHOD"),
    (hap_client.RpcReply(200, {"error": [14, "Unsupported Version"]}), "UNSUPPORTED_VERSION"),
    (hap_client.RpcReply(200, {"error": [5, "illegal Request"]}), "ILLEGAL_REQUEST"),
    (hap_client.RpcReply(200, {"error": [7, "something"]}), "OTHER"),
    (hap_client.RpcReply(200, {"error": []}), "OTHER"),
])
def test_classify(reply, klass):
    assert fuzzer.classify(reply) == klass


def test_fuzz_stops_at_the_first_decisive_version(monkeypatch):
    seen = []

    def fake_call(ip, port, service, method, version, params):
        seen.append(version)
        if version in ("1.0", "1.1"):
            return hap_client.RpcReply(200, {"error": [14, "Unsupported Version"]})
        return hap_client.RpcReply(200, {"result": [{"ok": 1}]})

    monkeypatch.setattr(fuzzer, "call", fake_call)
    findings = fuzzer.fuzz_method("h", 1, "system", "getX", sleep=lambda s: None)
    assert [(f["class"], f["version"]) for f in findings] == [("OK", "1.2")]
    assert seen == ["1.0", "1.1", "1.2"]


def test_fuzz_keeps_a_transport_error_next_to_the_decisive_answer(monkeypatch):
    def fake_call(ip, port, service, method, version, params):
        if version == "1.0":
            return hap_client.RpcReply(0, None, "timed out")
        if version == "1.1":
            return hap_client.RpcReply(200, {"error": [14, "Unsupported Version"]})
        return hap_client.RpcReply(200, {"error": [5, "illegal Request"]})

    monkeypatch.setattr(fuzzer, "call", fake_call)
    findings = fuzzer.fuzz_method("h", 1, "system", "getX", sleep=lambda s: None)
    assert [(f["class"], f["version"]) for f in findings] == [
        ("TRANSPORT", "1.0"), ("ILLEGAL_REQUEST", "1.2")]

    monkeypatch.setattr(fuzzer, "call", lambda *a: hap_client.RpcReply(0, None, "down"))
    findings = fuzzer.fuzz_method("h", 1, "system", "getX", sleep=lambda s: None)
    assert [f["class"] for f in findings] == ["TRANSPORT"] * len(fuzzer.VERSIONS_TO_TRY) + [
        "UNSUPPORTED_VERSION_ALL"]


def test_fuzz_records_a_method_no_version_accepts(monkeypatch):
    monkeypatch.setattr(fuzzer, "call", lambda *a: hap_client.RpcReply(
        200, {"error": [14, "Unsupported Version"]}))
    (finding,) = fuzzer.fuzz_method("h", 1, "system", "getX", sleep=lambda s: None)
    assert finding["class"] == "UNSUPPORTED_VERSION_ALL" and finding["version"] is None


def test_fuzz_filters_and_summarises(monkeypatch):
    monkeypatch.setattr(fuzzer, "call", lambda ip, port, s, m, v, p: hap_client.RpcReply(
        200, {"result": [{}]} if m == "getVersions" else {"error": [5, "illegal Request"]}))
    findings = fuzzer.fuzz("h", 1, "guide", None, sleep=lambda s: None)
    assert {f["service"] for f in findings} == {"guide"}
    assert len(findings) == len(fuzzer.CANDIDATES["guide"])
    only = fuzzer.fuzz("h", 1, None, "getVersions", sleep=lambda s: None)
    assert [f["service"] for f in only] == list(fuzzer.CANDIDATES)
    summary = fuzzer.summarize(findings)
    assert "ILLEGAL_REQUEST" in summary and "guide.getVersions v1.0: OK" in summary


def test_fuzzer_main_against_the_mock(device, tmp_path, capsys, monkeypatch):
    host, port = device
    monkeypatch.setattr(fuzzer, "VERSIONS_TO_TRY", ["1.0"])
    monkeypatch.setattr(fuzzer, "save_capture",
                        lambda prefix, payload, tool: tmp_path / f"{prefix}.json")
    assert fuzzer.main(["--target", host, "--port", str(port), "--service", "system",
                        "--method", "getSystemInformation"]) == 0
    out = capsys.readouterr().out
    assert "system.getSystemInformation v1.0: OK" in out and "Report saved" in out
