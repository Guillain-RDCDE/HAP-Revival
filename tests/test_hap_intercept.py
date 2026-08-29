"""Offline checks for the DNS wire format hap_intercept.py speaks.

No device, no sockets: these build and parse packets in memory. The point is
that a malformed answer would be invisible on the wire — the player would just
retry silently — so the encoding is worth pinning down.
"""

import socket
import struct

import hap_intercept


def query_packet(name: str, qtype: int = 1, transaction_id: bytes = b"\xab\xcd") -> bytes:
    """A minimal, uncompressed DNS query, the way a resolver sends one."""
    question = b""
    for label in name.split("."):
        question += bytes([len(label)]) + label.encode("ascii")
    question += b"\x00" + struct.pack("!HH", qtype, 1)
    header = transaction_id + struct.pack("!HHHHH", 0x0100, 1, 0, 0, 0)
    return header + question


def test_parse_question_reads_name_and_type():
    parsed = hap_intercept.parse_question(query_packet("info.update.sony.net"))
    assert parsed == ("info.update.sony.net", 1)


def test_parse_question_handles_aaaa():
    parsed = hap_intercept.parse_question(query_packet("opml.radiotime.com", qtype=28))
    assert parsed == ("opml.radiotime.com", 28)


def test_parse_question_rejects_a_compressed_question():
    # A pointer in the question would mean guessing at an offset we never read.
    packet = b"\xab\xcd" + struct.pack("!HHHHH", 0x0100, 1, 0, 0, 0) + b"\xc0\x0c"
    assert hap_intercept.parse_question(packet) is None


def test_parse_question_rejects_a_runt():
    assert hap_intercept.parse_question(b"\x00\x01") is None


def test_a_answer_keeps_the_transaction_id_and_question():
    query = query_packet("info.update.sony.net")
    reply = hap_intercept.build_a_answer(query, "192.168.1.100")

    assert reply[:2] == query[:2], "the resolver matches replies on this id"
    flags, qdcount, ancount = struct.unpack("!HHH", reply[2:8])
    assert flags == 0x8180
    assert (qdcount, ancount) == (1, 1)
    assert reply[12 : len(query)] == query[12:], "question echoed byte for byte"


def test_a_answer_carries_the_address_we_asked_for():
    reply = hap_intercept.build_a_answer(query_packet("x.example"), "192.168.1.100")
    assert reply[-4:] == socket.inet_aton("192.168.1.100")
    # 2 bytes of name pointer + type, class, ttl, rdlength (10) + 4 of address
    record = reply[-16:]
    assert record[:2] == b"\xc0\x0c"
    rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", record[2:12])
    assert (rtype, rclass, rdlength) == (1, 1, 4)
    assert ttl == hap_intercept.ANSWER_TTL_SEC


def test_empty_answer_is_noerror_with_no_records():
    query = query_packet("info.update.sony.net", qtype=28)
    reply = hap_intercept.build_empty_answer(query)

    assert reply[:2] == query[:2]
    flags, qdcount, ancount = struct.unpack("!HHH", reply[2:8])
    assert flags == 0x8180, "NOERROR, not a refusal — we want an IPv4 fallback"
    assert (qdcount, ancount) == (1, 0)
    assert reply[12:] == query[12:]
