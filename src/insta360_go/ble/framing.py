"""The 16-byte header the camera wraps every protobuf message in.

    offset  size  meaning
    0       2     TOTAL length, little-endian  (header + payload, NOT payload)
    2       2     reserved
    4       1     mode, 0x04 = message
    5       2     reserved
    7       2     command code, or an HTTP-ish status on replies
    9       1     content type, 0x02 = protobuf
    10      1     sequence number, 1..254
    11      2     reserved
    13      1     flags, bit 7 = last fragment
    14      2     reserved

The length field is the single most important detail. Published notes on newer
Insta360 cameras describe it as the payload length; on the GO 1 a payload-only
length is answered with a 7-byte reject frame, and the total length is answered
with 200. That one difference is the whole reason this protocol looked closed.
"""
from dataclasses import dataclass
from typing import Optional

from ..constants import IDLE_FRAME, NOTIFICATION_FLOOR

HEADER_LEN = 16
MODE_MESSAGE = 0x04
CONTENT_PROTOBUF = 0x02
FLAG_LAST = 0x80

STATUS_OK = 200

#: No legitimate reply comes close to this. A larger length field means the
#: stream has desynchronised - without this cap the reassembler would wait
#: forever for a frame that will never arrive.
MAX_FRAME = 4096


@dataclass
class Reply:
    status: int
    payload: bytes

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def build_frame(command: int, payload: bytes = b"", seq: int = 1) -> bytes:
    if not 1 <= seq <= 254:
        raise ValueError("sequence number must be 1..254")
    h = bytearray(HEADER_LEN)
    h[0:2] = (HEADER_LEN + len(payload)).to_bytes(2, "little")
    h[4] = MODE_MESSAGE
    h[7:9] = command.to_bytes(2, "little")
    h[9] = CONTENT_PROTOBUF
    h[10] = seq
    h[13] = FLAG_LAST
    return bytes(h) + payload


def parse_frame(data: bytes) -> Optional[Reply]:
    """Parse one complete frame, or None if `data` is short."""
    if len(data) < HEADER_LEN:
        return None
    total = int.from_bytes(data[0:2], "little")
    if len(data) < total:
        return None
    return Reply(int.from_bytes(data[7:9], "little"), data[HEADER_LEN:total])


class Reassembler:
    """Accumulates BLE notifications and hands back genuine replies.

    Two kinds of traffic have to be discarded or the caller sees nonsense:
      * the 7-byte idle frame the camera emits while doing nothing
      * asynchronous notifications (status >= 8192) such as capture-state
        changes, which arrive unsolicited and are not a reply to anything
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.skipped_idle = 0
        self.skipped_notifications: list[int] = []

    def feed(self, chunk: bytes) -> Optional[Reply]:
        self._buf.extend(chunk)
        while len(self._buf) >= 2:
            total = int.from_bytes(self._buf[0:2], "little")

            if total == len(IDLE_FRAME):
                if len(self._buf) < total:
                    return None
                if bytes(self._buf[:total]) == IDLE_FRAME:
                    del self._buf[:total]
                    self.skipped_idle += 1
                    continue
                del self._buf[:1]
                continue

            if total < HEADER_LEN or total > MAX_FRAME:
                del self._buf[:1]                 # cannot be a frame; resync
                continue
            if len(self._buf) < HEADER_LEN:
                return None                       # need the header to validate
            if not self._header_looks_real():
                del self._buf[:1]                 # plausible length, bogus header
                continue
            if len(self._buf) < total:
                return None

            reply = parse_frame(bytes(self._buf[:total]))
            del self._buf[:total]
            if reply is None:
                return None
            if reply.status >= NOTIFICATION_FLOOR:
                self.skipped_notifications.append(reply.status)
                continue
            return reply
        return None

    def _header_looks_real(self) -> bool:
        """A length alone is not enough to resync on - a stray byte can make
        garbage look like a plausible frame. The mode and content-type bytes
        are effectively a signature, so require them too."""
        return (self._buf[4] == MODE_MESSAGE
                and self._buf[9] == CONTENT_PROTOBUF)

    def reset(self) -> None:
        self._buf.clear()
