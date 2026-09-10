"""High-level camera operations built on the BLE transport."""
from __future__ import annotations

import time

from .ble.codec import encode_varint, encode_zigzag, find, iter_fields, message, tag
from .ble.transport import Camera, CameraError
from .constants import (
    BUTTON_FIELD,
    FUNCTION_MODE,
    GET_OPTIONS,
    GET_PHOTOGRAPHY_OPTIONS,
    NORMAL_VIDEO,
    SET_OPTIONS,
    SET_PHOTOGRAPHY_OPTIONS,
    Option,
    Photo,
)


class WriteRejected(CameraError):
    """The camera returned a non-200 status for a write."""


class WriteIgnored(CameraError):
    """The camera accepted the write but the value did not change.

    This is the GO 1's signature failure: several options return 200 and
    persist nothing. Reporting it distinctly matters, because "accepted" and
    "applied" are not the same thing on this firmware.
    """


# ----------------------------------------------------------------- options
async def get_option(cam: Camera, option: int):
    reply = await cam.request(GET_OPTIONS, tag(1) + encode_varint(option))
    if not reply.ok:
        return None
    return find(reply.payload, 2, option)


async def set_option(cam: Camera, option: int, value: int, *,
                     verify: bool = True) -> int | None:
    inner = tag(option) + encode_varint(value)
    payload = tag(1) + encode_varint(option) + message(2, inner)
    reply = await cam.request(SET_OPTIONS, payload)
    if not reply.ok:
        raise WriteRejected(f"option {option}: camera returned {reply.status}")
    if not verify:
        return None
    return await get_option(cam, option)


# ------------------------------------------------- photography options
async def get_photo_option(cam: Camera, option: int,
                           mode: int = NORMAL_VIDEO):
    payload = tag(1) + encode_varint(option) + tag(2) + encode_varint(mode)
    reply = await cam.request(GET_PHOTOGRAPHY_OPTIONS, payload)
    if not reply.ok:
        return None
    return find(reply.payload, 2, option)


async def set_photo_option(cam: Camera, option: int, value: int,
                           mode: int = NORMAL_VIDEO, *,
                           verify: bool = True) -> int | None:
    inner = tag(option) + encode_varint(value)
    payload = (tag(1) + encode_varint(option) + message(2, inner)
               + tag(3) + encode_varint(mode))
    reply = await cam.request(SET_PHOTOGRAPHY_OPTIONS, payload)
    if not reply.ok:
        raise WriteRejected(
            f"photography option {option} (mode {mode}): status {reply.status}")
    if not verify:
        return None
    return await get_photo_option(cam, option, mode)


# ------------------------------------------------------- recording length
async def get_record_duration(cam: Camera, mode: int = NORMAL_VIDEO):
    return await get_photo_option(cam, Photo.RECORD_DURAION, mode)


async def set_record_duration(cam: Camera, seconds: int,
                              mode: int = NORMAL_VIDEO) -> int:
    """Set how long a clip records before the camera stops itself.

    This is the field that actually works. Options.capture_time_limit looks
    like the right one, accepts writes and persists them, and is ignored.
    """
    if seconds < 1:
        raise ValueError("seconds must be positive")
    got = await set_photo_option(cam, Photo.RECORD_DURAION, seconds, mode)
    if got != seconds:
        raise WriteIgnored(
            f"asked for {seconds}s, camera reports {got}. "
            f"Mode {mode} may not support a custom duration.")
    return got


async def durations(cam: Camera) -> dict[int, int | None]:
    """record_duration for every function mode."""
    out: dict[int, int | None] = {}
    for mode in sorted(FUNCTION_MODE):
        try:
            out[mode] = await get_photo_option(cam, Photo.RECORD_DURAION, mode)
        except CameraError:
            out[mode] = None
    return out


# ---------------------------------------------------------------- buttons
async def get_buttons(cam: Camera) -> dict[int, int]:
    raw = await get_option(cam, Option.BUTTON_PRESS_OPTIONS)
    if not isinstance(raw, (bytes, bytearray)):
        return {}
    return {f: v for f, w, v in iter_fields(raw) if w == 0}


async def set_buttons(cam: Camera, mapping: dict[int, int]) -> dict[int, int]:
    """Write the button map.

    The full map is always sent, with unchanged buttons carrying their current
    value, rather than relying on the DO_NOT_CHANGE sentinel - if the firmware
    ever treated 0 as a literal mode instead of "leave alone", that sentinel
    would silently disable buttons.
    """
    current = await get_buttons(cam)
    merged = {**current, **mapping}
    for field in merged:
        if field not in BUTTON_FIELD:
            raise ValueError(f"unknown button field {field}")
    inner = b"".join(tag(f) + encode_varint(v) for f, v in sorted(merged.items()))
    options = message(Option.BUTTON_PRESS_OPTIONS, inner)
    payload = tag(1) + encode_varint(Option.BUTTON_PRESS_OPTIONS) + message(2, options)
    reply = await cam.request(SET_OPTIONS, payload)
    if not reply.ok:
        raise WriteRejected(f"button map: camera returned {reply.status}")
    return await get_buttons(cam)


# ------------------------------------------------------------------ clock
async def set_clock(cam: Camera, when: float | None = None) -> None:
    """Set the camera clock. Its own clock resets to 2020, which is why
    recordings come off the card with wrong dates."""
    epoch = int(when if when is not None else time.time())
    offset = -int(time.altzone if time.daylight else time.timezone)
    inner = tag(Option.LOCAL_TIME) + encode_varint(epoch)
    payload = tag(1) + encode_varint(Option.LOCAL_TIME) + message(2, inner)
    reply = await cam.request(SET_OPTIONS, payload)
    if not reply.ok:
        raise WriteRejected(f"clock: camera returned {reply.status}")
    inner = tag(Option.TIME_ZONE) + encode_zigzag(offset)
    payload = tag(1) + encode_varint(Option.TIME_ZONE) + message(2, inner)
    await cam.request(SET_OPTIONS, payload)
    # Neither field reads back on this firmware, so there is nothing to verify
    # here; confirmation is that new recordings carry the right filename date.


async def info(cam: Camera) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, opt in (("serial", Option.SERIAL_NUMBER),
                     ("firmware", Option.FIRMWARE_REVISION),
                     ("model", Option.CAMERA_TYPE)):
        val = await get_option(cam, opt)
        if isinstance(val, (bytes, bytearray)):
            try:
                val = val.decode("utf-8")
            except UnicodeDecodeError:
                val = val.hex()
        out[key] = val
    out["record_duration"] = await get_record_duration(cam)
    return out
