"""Protocol constants verified against real GO 1 hardware (firmware v0.4.9.5).

Every value here was confirmed by round-tripping against a camera: written,
read back, and where applicable observed changing recorded footage. Values we
could not verify are absent rather than guessed.

The full 74-descriptor schema can be regenerated from an official APK with
`tools/extract_protocol.py`; see docs/PROTOCOL.md.
"""
from __future__ import annotations

# --- GATT ------------------------------------------------------------------
SERVICE = "0000be80-0000-1000-8000-00805f9b34fb"
CHAR_WRITE = "0000be81-0000-1000-8000-00805f9b34fb"   # app  -> camera
CHAR_NOTIFY = "0000be82-0000-1000-8000-00805f9b34fb"  # camera -> app

# --- MessageCode -----------------------------------------------------------
START_CAPTURE = 4
STOP_CAPTURE = 5
SET_OPTIONS = 7
GET_OPTIONS = 8
SET_PHOTOGRAPHY_OPTIONS = 9
GET_PHOTOGRAPHY_OPTIONS = 10

#: Replies at or above this value are asynchronous camera notifications,
#: not the answer to the command you just sent. They must be skipped.
NOTIFICATION_FLOOR = 8192

#: The camera emits this 7-byte frame when idle. It is not a reply.
IDLE_FRAME = bytes.fromhex("07000000050000")

# --- OptionType (camera-wide; field number in Options matches the enum) -----
class Option:
    CAPTURE_TIME_LIMIT = 7      # accepted and persisted, but IGNORED by GO 1
    BATTERY_STATUS = 11
    LOCAL_TIME = 12
    TIME_ZONE = 13
    MUTE = 14
    SERIAL_NUMBER = 15
    BUTTON_PRESS_OPTIONS = 17
    STORAGE_STATE = 20
    SELF_TIMER = 23
    LOG_MODE = 28
    FIRMWARE_REVISION = 30
    SPORT_MODE_ENABLE = 35
    VIDEO_SUB_MODE = 41
    CAMERA_TYPE = 48
    TELEVISION_SYSTEM = 57

# --- PhotographyOptionType (per FunctionMode) ------------------------------
class Photo:
    BRIGHTNESS = 2
    CONTRAST = 3
    SATURATION = 4
    HUE = 5
    SHARPNESS = 6
    EXPOSURE_BIAS = 7
    AE_METER_MODE = 11
    WHITE_BALANCE = 13
    FLICKER = 14
    LOG_MODE_ENABLE = 18
    VIDEO_EXPOSURE_OPTIONS = 21
    SPORT_MODE_ENABLE = 23
    VIDEO_ISO_TOP_LIMIT = 24
    SELF_TIMER = 26
    #: The real recording-length control. Note Insta360's typo in the enum.
    RECORD_DURAION = 29
    RECORD_DURATION = 29        # friendlier alias

FUNCTION_MODE = {
    0: "normal", 1: "live_stream", 2: "mobile_timelapse", 3: "interval_shooting",
    4: "slow_motion", 5: "burst", 6: "photo", 7: "normal_video", 8: "hdr_photo",
    9: "hdr_video", 10: "interval_video", 11: "static_timelapse", 12: "timeshift",
    13: "night_photo",
}
#: The mode a button press records in, and therefore the one that matters.
NORMAL_VIDEO = 7

BUTTON_FIELD = {
    1: "click", 2: "double_click", 3: "triple_click", 4: "long_press",
    5: "short_press", 6: "off_click", 7: "off_double_click",
    8: "off_triple_click", 9: "off_long_press", 10: "off_short_press",
}
BUTTON_MODE = {
    0: "leave_unchanged", 1: "do_nothing", 2: "shut_down", 3: "take_photo",
    4: "record_video", 5: "self_timer", 6: "timelapse", 7: "slow_motion",
    8: "timelapse_video", 9: "interval_shooting", 10: "interval_video",
    11: "hdr_photo", 12: "static_timelapse", 13: "calibrate_gyro",
}

FLICKER = {"auto": 0, "60hz": 1, "50hz": 2}
WHITE_BALANCE = {"auto": 0, "2700k": 1, "4000k": 2, "5000k": 3,
                 "6500k": 4, "7500k": 5}

#: Options this firmware accepts writes for but demonstrably does not act on.
KNOWN_DECOYS = {Option.CAPTURE_TIME_LIMIT}

