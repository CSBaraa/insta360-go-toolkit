"""BLE transport: find the camera, connect, exchange one message at a time."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..constants import CHAR_NOTIFY, CHAR_WRITE, SERVICE
from .framing import Reassembler, Reply, build_frame


class CameraError(RuntimeError):
    pass


class NotConnected(CameraError):
    pass


class Timeout(CameraError):
    pass


@dataclass
class Found:
    address: str
    name: str
    rssi: int


async def discover(timeout: float = 10.0) -> list[Found]:
    """Return GO cameras that are advertising. The camera must be powered on."""
    from bleak import BleakScanner

    out: list[Found] = []
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for address, (device, adv) in found.items():
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        name = adv.local_name or device.name or ""
        if any(u.startswith(SERVICE[:8]) for u in uuids) or name.startswith("GO"):
            out.append(Found(address, name or "(unnamed)", adv.rssi or -999))
    return sorted(out, key=lambda f: -f.rssi)


class Camera:
    """One BLE connection to a GO 1.

        async with Camera(address) as cam:
            reply = await cam.request(GET_OPTIONS, payload)

    The camera answers one command at a time, so requests are serialised behind
    a lock; concurrent callers would otherwise read each other's replies.
    """

    def __init__(self, address: str, name: str = "") -> None:
        self.address = address
        self.name = name
        self._client = None
        self._rx = Reassembler()
        # Built lazily: on Python 3.9 an asyncio primitive binds to the loop
        # that exists when it is constructed, so building these in __init__
        # breaks any caller that creates a Camera before entering the loop.
        self._replies: asyncio.Queue | None = None
        self._lock: asyncio.Lock | None = None
        self._seq = 0

    def _ensure_primitives(self) -> None:
        if self._replies is None:
            self._replies = asyncio.Queue()
        if self._lock is None:
            self._lock = asyncio.Lock()

    # ------------------------------------------------------------- lifecycle
    async def connect(self, timeout: float = 25.0) -> Camera:
        from bleak import BleakClient

        self._ensure_primitives()
        client = BleakClient(self.address, timeout=timeout)
        await client.connect()
        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        self._client = client
        return self

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None

    async def __aenter__(self) -> Camera:
        return await self.connect()

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    # ---------------------------------------------------------------- io
    def _on_notify(self, _handle, data: bytearray) -> None:
        if self._replies is None:
            return
        reply = self._rx.feed(bytes(data))
        while reply is not None:
            self._replies.put_nowait(reply)
            reply = self._rx.feed(b"")

    def _next_seq(self) -> int:
        self._seq = self._seq % 254 + 1
        return self._seq

    async def request(self, command: int, payload: bytes = b"",
                      timeout: float = 8.0) -> Reply:
        """Send one command and wait for its reply.

        Raises Timeout rather than returning a sentinel: a command that gets no
        answer is not the same as one that answered "no", and conflating them
        is how a failed read gets misreported as a rejected write.
        """
        if not self.connected:
            raise NotConnected("not connected to the camera")
        self._ensure_primitives()
        async with self._lock:
            while not self._replies.empty():        # drop anything stale
                self._replies.get_nowait()
            frame = build_frame(command, payload, self._next_seq())
            await self._client.write_gatt_char(CHAR_WRITE, frame, response=True)
            try:
                return await asyncio.wait_for(self._replies.get(), timeout)
            except asyncio.TimeoutError:
                raise Timeout(
                    f"no reply to command {command} within {timeout}s"
                ) from None
