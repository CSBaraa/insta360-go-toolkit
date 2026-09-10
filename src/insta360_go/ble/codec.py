"""Just enough protobuf to talk to the camera.

The camera speaks protobuf, but the messages we need are tiny and their field
numbers are known, so a full protobuf runtime would be a heavy dependency for
what amounts to a few varints. This module is the whole codec.
"""
from collections.abc import Iterator
from typing import Union

Value = Union[int, bytes]


def encode_varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative values need zigzag encoding; use encode_zigzag")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def encode_zigzag(n: int) -> bytes:
    """For sint32 fields such as Options.time_zone_seconds_from_GMT."""
    return encode_varint((n << 1) ^ (n >> 31))


def decode_varint(buf: bytes, pos: int = 0) -> tuple[int, int]:
    n = shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, pos
        shift += 7
    raise ValueError("truncated varint")


def tag(field: int, wire: int = 0) -> bytes:
    return encode_varint((field << 3) | wire)


def message(field: int, body: bytes) -> bytes:
    """Encode a length-delimited submessage."""
    return tag(field, 2) + encode_varint(len(body)) + body


def iter_fields(buf: bytes) -> Iterator[tuple[int, int, Value]]:
    """Yield (field_number, wire_type, value). Stops cleanly on malformed input.

    Wire type 0 yields an int; types 1, 2 and 5 yield bytes.
    """
    pos = 0
    while pos < len(buf):
        try:
            key, pos = decode_varint(buf, pos)
        except ValueError:
            return
        field, wire = key >> 3, key & 7
        if wire == 0:
            try:
                val, pos = decode_varint(buf, pos)
            except ValueError:
                return
            yield field, wire, val
        elif wire == 2:
            try:
                ln, pos = decode_varint(buf, pos)
            except ValueError:
                return
            yield field, wire, buf[pos:pos + ln]
            pos += ln
        elif wire == 5:
            yield field, wire, buf[pos:pos + 4]
            pos += 4
        elif wire == 1:
            yield field, wire, buf[pos:pos + 8]
            pos += 8
        else:
            return


def find(buf: bytes, *path: int):
    """Follow nested field numbers, e.g. find(body, 2, 29) -> value.field_29."""
    cur = buf
    for i, want in enumerate(path):
        last = i == len(path) - 1
        for field, wire, val in iter_fields(cur):
            if field != want:
                continue
            if last:
                return val
            if wire == 2:
                cur = val
                break
        else:
            return None
    return None
