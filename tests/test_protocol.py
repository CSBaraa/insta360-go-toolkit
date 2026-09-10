"""Tests built from traffic actually captured from an Insta360 GO 1.

Every hex string below was recorded from a real camera (firmware v0.4.9.5).
No camera is needed to run these.
"""
import pytest

from insta360_go.ble.codec import (
    decode_varint,
    encode_varint,
    encode_zigzag,
    find,
    iter_fields,
    message,
    tag,
)
from insta360_go.ble.framing import HEADER_LEN, STATUS_OK, Reassembler, build_frame, parse_frame
from insta360_go.constants import (
    GET_OPTIONS,
    IDLE_FRAME,
    Option,
)

# --- captured from the camera ---------------------------------------------
GET_OPTIONS_REQUEST = bytes.fromhex("1400000004000008000201000080000008070837")
GET_OPTIONS_REPLY = bytes.fromhex(
    "16000000040000c8000203000080001408071202" "3800")
BUTTON_REPLY_PAYLOAD = bytes.fromhex(
    "081112138a011008031008180720082803300448005001")
BUTTON_PRESS_BYTES = bytes.fromhex("08031008180720082803300448005001")


class TestVarint:
    @pytest.mark.parametrize("n", [0, 1, 7, 55, 60, 127, 128, 300, 3600, 65535])
    def test_roundtrip(self, n):
        assert decode_varint(encode_varint(n))[0] == n

    def test_known_encodings(self):
        assert encode_varint(60) == b"\x3c"
        assert encode_varint(300) == bytes.fromhex("ac02")

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            encode_varint(-1)

    def test_zigzag(self):
        assert encode_zigzag(0) == b"\x00"
        assert decode_varint(encode_zigzag(-1))[0] == 1


class TestFraming:
    def test_reproduces_the_request_that_worked(self):
        """The exact frame the camera answered with 200."""
        payload = b"".join(tag(1) + encode_varint(t) for t in (7, 55))
        assert build_frame(GET_OPTIONS, payload, seq=1) == GET_OPTIONS_REQUEST

    def test_length_field_is_total_not_payload(self):
        """The detail that made this protocol look closed."""
        frame = build_frame(GET_OPTIONS, b"\x08\x07")
        assert int.from_bytes(frame[0:2], "little") == HEADER_LEN + 2 == len(frame)

    def test_parses_the_real_reply(self):
        reply = parse_frame(GET_OPTIONS_REPLY)
        assert reply.status == STATUS_OK and reply.ok
        assert reply.payload == bytes.fromhex("08071202 3800".replace(" ", ""))

    def test_short_data_returns_none(self):
        assert parse_frame(b"\x00" * 4) is None
        assert parse_frame(GET_OPTIONS_REPLY[:18]) is None

    @pytest.mark.parametrize("seq", [0, 255, 300])
    def test_bad_sequence_rejected(self, seq):
        with pytest.raises(ValueError):
            build_frame(GET_OPTIONS, b"", seq=seq)


class TestReassembler:
    def test_reply_split_across_notifications(self):
        """The camera really does split replies; ours arrived as 20B + 2B."""
        r = Reassembler()
        assert r.feed(GET_OPTIONS_REPLY[:20]) is None
        reply = r.feed(GET_OPTIONS_REPLY[20:])
        assert reply is not None and reply.ok

    def test_skips_idle_frames(self):
        r = Reassembler()
        for _ in range(5):
            assert r.feed(IDLE_FRAME) is None
        assert r.skipped_idle == 5
        assert r.feed(GET_OPTIONS_REPLY).ok

    def test_skips_async_notifications(self):
        """Status 8195 arrived unsolicited and was mistaken for a reply."""
        notif = bytearray(GET_OPTIONS_REPLY)
        notif[7:9] = (8195).to_bytes(2, "little")
        r = Reassembler()
        assert r.feed(bytes(notif)) is None
        assert r.skipped_notifications == [8195]
        assert r.feed(GET_OPTIONS_REPLY).ok

    def test_idle_then_split_reply(self):
        r = Reassembler()
        assert r.feed(IDLE_FRAME + GET_OPTIONS_REPLY[:10]) is None
        assert r.feed(GET_OPTIONS_REPLY[10:]).ok


class TestDecoding:
    def test_capture_time_limit_from_real_reply(self):
        reply = parse_frame(GET_OPTIONS_REPLY)
        assert find(reply.payload, 2, Option.CAPTURE_TIME_LIMIT) == 0

    def test_button_mapping_from_real_reply(self):
        press = find(BUTTON_REPLY_PAYLOAD, 2, Option.BUTTON_PRESS_OPTIONS)
        assert press == BUTTON_PRESS_BYTES
        got = {f: v for f, w, v in iter_fields(press) if w == 0}
        assert got == {1: 3, 2: 8, 3: 7, 4: 8, 5: 3, 6: 4, 9: 0, 10: 1}

    def test_button_encoding_reproduces_camera_bytes(self):
        """Re-encoding what the camera sent must be byte-identical."""
        mapping = {1: 3, 2: 8, 3: 7, 4: 8, 5: 3, 6: 4, 9: 0, 10: 1}
        out = b"".join(tag(f) + encode_varint(v) for f, v in sorted(mapping.items()))
        assert out == BUTTON_PRESS_BYTES

    def test_iter_fields_survives_garbage(self):
        assert list(iter_fields(b"\xff\xff\xff")) == []
        assert list(iter_fields(b"")) == []


class TestPayloadBuilders:
    def test_set_record_duration_payload(self):
        """SetPhotographyOptions{option_types=29, value={29: 60}, function_mode=7}"""
        inner = tag(29) + encode_varint(60)
        payload = tag(1) + encode_varint(29) + message(2, inner) + tag(3) + encode_varint(7)
        assert payload.hex() == "081d1203e8013c1807"
        assert find(payload, 2, 29) == 60


class TestReassemblerEdgeCases:
    """Regression tests for bugs found while building this."""

    def test_idle_frames_drained_immediately(self):
        """Idle frames are 7 bytes; waiting for a full 16-byte header before
        inspecting the buffer let them accumulate and desynchronise the stream."""
        r = Reassembler()
        for i in range(1, 6):
            r.feed(IDLE_FRAME)
            assert r.skipped_idle == i

    def test_byte_at_a_time_delivery(self):
        r = Reassembler()
        for b in GET_OPTIONS_REPLY[:-1]:
            assert r.feed(bytes([b])) is None
        assert r.feed(GET_OPTIONS_REPLY[-1:]).ok

    def test_two_replies_in_one_chunk(self):
        r = Reassembler()
        assert r.feed(GET_OPTIONS_REPLY + GET_OPTIONS_REPLY).ok
        assert r.feed(b"").ok

    def test_resyncs_after_garbage(self):
        r = Reassembler()
        r.feed(b"\x01\x00")
        assert r.feed(GET_OPTIONS_REPLY).ok

    def test_absurd_length_does_not_hang(self):
        """A lost byte makes the length field read as garbage; without a sanity
        cap the reassembler waits forever for a frame that never arrives."""
        r = Reassembler()
        r.feed(b"\xff\xff" + b"\x00" * 4)
        assert r.feed(GET_OPTIONS_REPLY).ok
