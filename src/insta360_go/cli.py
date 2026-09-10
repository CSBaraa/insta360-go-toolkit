"""`go1` - command line control for an Insta360 GO (1st generation)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from . import __version__
from .ble.transport import Camera, CameraError, discover
from .camera import (
    durations,
    get_buttons,
    get_option,
    get_photo_option,
    get_record_duration,
    info,
    set_buttons,
    set_clock,
    set_option,
    set_photo_option,
    set_record_duration,
)
from .constants import (
    BUTTON_FIELD,
    BUTTON_MODE,
    FUNCTION_MODE,
    KNOWN_DECOYS,
    NORMAL_VIDEO,
)

STATE = Path(os.environ.get("XDG_STATE_HOME",
                            Path.home() / ".local/state")) / "insta360-go.json"
BTN_BY_NAME = {v: k for k, v in BUTTON_FIELD.items()}
MODE_BY_NAME = {v: k for k, v in BUTTON_MODE.items()}
FMODE_BY_NAME = {v: k for k, v in FUNCTION_MODE.items()}


def _remember(address: str, name: str = "") -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"address": address, "name": name}))
    except OSError:
        pass


def _recall() -> str | None:
    try:
        return json.loads(STATE.read_text()).get("address")
    except (OSError, ValueError):
        return None


async def _resolve(address: str | None) -> str:
    if address:
        return address
    remembered = _recall()
    if remembered:
        return remembered
    print("no camera remembered, scanning... (power the camera on)")
    found = await discover()
    if not found:
        raise SystemExit(
            "No GO camera found.\n"
            "  * hold the button until it buzzes to power it on\n"
            "  * take it out of the charge case\n"
            "  * on macOS, run this from a terminal that has Bluetooth permission")
    _remember(found[0].address, found[0].name)
    print(f"using {found[0].name} ({found[0].address})")
    return found[0].address


async def _open(address: str | None) -> Camera:
    addr = await _resolve(address)
    cam = Camera(addr)
    await cam.connect()
    return cam


# --------------------------------------------------------------- commands
async def cmd_scan(args) -> int:
    found = await discover(args.timeout)
    if not found:
        print("nothing found. power the camera on and try again.")
        return 1
    for f in found:
        print(f"  {f.address}  {f.name}  {f.rssi}dBm")
    _remember(found[0].address, found[0].name)
    return 0


async def cmd_info(args) -> int:
    cam = await _open(args.address)
    try:
        data = await info(cam)
        for k, v in data.items():
            print(f"  {k:18s} {v}")
    finally:
        await cam.disconnect()
    return 0


async def cmd_duration(args) -> int:
    cam = await _open(args.address)
    try:
        mode = args.mode
        if args.seconds is None:
            if args.all:
                for m, secs in (await durations(cam)).items():
                    star = "  <- button records in this mode" if m == NORMAL_VIDEO else ""
                    print(f"  {m:2d} {FUNCTION_MODE[m]:18s} {str(secs) + 's' if secs is not None else '-':>6}{star}")
            else:
                print(f"  {FUNCTION_MODE[mode]}: {await get_record_duration(cam, mode)}s")
            return 0
        before = await get_record_duration(cam, mode)
        print(f"  {FUNCTION_MODE[mode]}: {before}s -> {args.seconds}s")
        if args.dry_run:
            print("  dry run, nothing sent")
            return 0
        after = await set_record_duration(cam, args.seconds, mode)
        print(f"  confirmed: {after}s")
        print("\n  Record a clip and check it before trusting this - the camera\n"
              "  reports some settings it does not act on.")
    finally:
        await cam.disconnect()
    return 0


async def cmd_buttons(args) -> int:
    cam = await _open(args.address)
    try:
        current = await get_buttons(cam)
        if not args.set:
            for field, mode in sorted(current.items()):
                print(f"  {BUTTON_FIELD.get(field, field):18s} {BUTTON_MODE.get(mode, mode)}")
            return 0
        changes = {}
        for pair in args.set:
            if "=" not in pair:
                raise SystemExit(f"expected button=mode, got {pair!r}")
            btn, mode = pair.split("=", 1)
            if btn not in BTN_BY_NAME:
                raise SystemExit(f"unknown button {btn!r}. choices: {', '.join(BTN_BY_NAME)}")
            if mode not in MODE_BY_NAME:
                raise SystemExit(f"unknown mode {mode!r}. choices: {', '.join(MODE_BY_NAME)}")
            changes[BTN_BY_NAME[btn]] = MODE_BY_NAME[mode]
        for f, v in changes.items():
            print(f"  {BUTTON_FIELD[f]:18s} {BUTTON_MODE.get(current.get(f))} -> {BUTTON_MODE[v]}")
        if args.dry_run:
            print("  dry run, nothing sent")
            return 0
        after = await set_buttons(cam, changes)
        ok = all(after.get(f) == v for f, v in changes.items())
        print("  confirmed" if ok else f"  camera reports {after} - not what we asked")
    finally:
        await cam.disconnect()
    return 0


async def cmd_clock(args) -> int:
    cam = await _open(args.address)
    try:
        if args.dry_run:
            print("  would set the camera clock from this computer")
            print("  dry run, nothing sent")
            return 0
        await set_clock(cam)
        print("  clock set. New recordings will carry today's date.")
        print("  (this firmware does not read the clock back, so the filename\n"
              "   date on the next clip is the confirmation)")
    finally:
        await cam.disconnect()
    return 0


async def cmd_get(args) -> int:
    cam = await _open(args.address)
    try:
        if args.photography:
            val = await get_photo_option(cam, args.option, args.mode)
        else:
            val = await get_option(cam, args.option)
        print(f"  {val!r}")
        if args.option in KNOWN_DECOYS and not args.photography:
            print("  note: this option is known to be ignored by GO 1 firmware")
    finally:
        await cam.disconnect()
    return 0


async def cmd_set(args) -> int:
    cam = await _open(args.address)
    try:
        if args.option in KNOWN_DECOYS and not args.photography:
            print("  warning: GO 1 accepts and persists this option but ignores it")
        if args.dry_run:
            print("  dry run, nothing sent")
            return 0
        if args.photography:
            got = await set_photo_option(cam, args.option, args.value, args.mode)
        else:
            got = await set_option(cam, args.option, args.value)
        print(f"  camera reports: {got!r}")
    finally:
        await cam.disconnect()
    return 0


def cmd_export(args) -> int:
    from .media.server import serve
    serve(port=args.port, open_browser=not args.no_browser)
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="go1", description="Control an Insta360 GO (1st gen) over Bluetooth.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-a", "--address", help="camera BLE address (remembered after first use)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="find nearby cameras")
    s.add_argument("--timeout", type=float, default=10.0)
    s.set_defaults(func=cmd_scan, is_async=True)

    s = sub.add_parser("info", help="serial, firmware, current recording length")
    s.set_defaults(func=cmd_info, is_async=True)

    s = sub.add_parser("duration", help="get or set the recording length")
    s.add_argument("seconds", nargs="?", type=int)
    s.add_argument("--mode", type=int, default=NORMAL_VIDEO,
                   help=f"function mode (default {NORMAL_VIDEO}, normal video)")
    s.add_argument("--all", action="store_true", help="show every mode")
    s.add_argument("-n", "--dry-run", action="store_true")
    s.set_defaults(func=cmd_duration, is_async=True)

    s = sub.add_parser("buttons", help="show or change the button map")
    s.add_argument("set", nargs="*", metavar="BUTTON=MODE",
                   help="e.g. triple_click=record_video")
    s.add_argument("-n", "--dry-run", action="store_true")
    s.set_defaults(func=cmd_buttons, is_async=True)

    s = sub.add_parser("clock", help="set the camera clock from this computer")
    s.add_argument("-n", "--dry-run", action="store_true")
    s.set_defaults(func=cmd_clock, is_async=True)

    s = sub.add_parser("get", help="read a raw option by number")
    s.add_argument("option", type=int)
    s.add_argument("-p", "--photography", action="store_true")
    s.add_argument("--mode", type=int, default=NORMAL_VIDEO)
    s.set_defaults(func=cmd_get, is_async=True)

    s = sub.add_parser("set", help="write a raw option by number")
    s.add_argument("option", type=int)
    s.add_argument("value", type=int)
    s.add_argument("-p", "--photography", action="store_true")
    s.add_argument("--mode", type=int, default=NORMAL_VIDEO)
    s.add_argument("-n", "--dry-run", action="store_true")
    s.set_defaults(func=cmd_set, is_async=True)

    s = sub.add_parser("export", help="browse and export footage in a browser")
    s.add_argument("--port", type=int, default=8731)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(func=cmd_export, is_async=False)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "is_async", False):
            return asyncio.run(args.func(args))
        return args.func(args)
    except CameraError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
