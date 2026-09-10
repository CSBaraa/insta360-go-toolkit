# insta360-go-toolkit

Control an **Insta360 GO (1st generation, 2019)** and export its footage — from a
computer, over Bluetooth, without the phone app.

> Insta360 removed the GO app from the App Store on **29 March 2026**, and the
> current Insta360 app does not support this camera. If you uninstalled it, or
> never had it, there is no supported way to change any setting on your camera.
> Insta360's own notice puts it plainly: without the app, "operations such as
> parameter settings will not be possible."
>
> This project gives those settings back.

*Not affiliated with or endorsed by Insta360 / Arashi Vision.*

---

## What it does

```console
$ go1 scan
  3737F9DB-774B-1ECA-E8D2-CF2757C71DC9  GO V55BQP  -47dBm

$ go1 info
  serial             IGS3519NV55BQP
  firmware           v0.4.9.5
  model              Insta360 Go
  record_duration    15

$ go1 duration 60
  normal_video: 15s -> 60s
  confirmed: 60s
```

That last one is the reason this exists. A GO 1 stuck at 15-second clips has no
other way back.

- **Recording length** — 15 s, 30 s, 60 s, up to the 5-minute FPV length
- **Button mapping** — what single, double, triple and long press each do
- **Clock** — the camera's own clock resets to 2020, so every file is misdated
- **Any option by number** — `go1 get` / `go1 set`, with the known decoys flagged
- **Footage export** — browse, preview, reframe and convert `.insv` in a browser

## Install

Needs Python 3.9+, and `ffmpeg` for the export side.

```bash
pip install insta360-go-toolkit
```

**macOS:** run from a terminal that has Bluetooth permission (System Settings →
Privacy & Security → Bluetooth). A process without it is killed the moment it
touches CoreBluetooth.

## Quick start

Power the camera on — hold the button until it buzzes — and take it out of the
charge case. It sleeps quickly, so run commands promptly.

```bash
go1 scan                    # find it; the address is remembered afterwards
go1 duration --all          # recording length for every capture mode
go1 duration 60             # set normal video to 60 seconds
go1 buttons                 # show the button map
go1 buttons triple_click=record_video
go1 clock                   # fix the 2020 date on new recordings
go1 export                  # browse and export footage in a browser
```

Add `-n` / `--dry-run` to any write to see what it would send.

## What it touches

Nothing is written to your camera unless you run a command that says so.
Installing, importing, `scan`, `info`, `get` and `export` never modify it.

| Command | Camera |
|---|---|
| `scan` `info` `get` `export` | read-only |
| `duration` (no value) `buttons` (no args) | read-only |
| `duration 60` `buttons btn=mode` `clock` `set` | writes — all support `-n` / `--dry-run` |

Only settings are implemented. There is no firmware-flashing path and no file
deletion, and a 20-second button hold factory-resets the camera if you want out.

**You do not need the Insta360 app or its APK to use this.** The values needed
to talk to the camera are ordinary constants in `constants.py`, and the only
runtime dependency is `bleak`. The APK is used solely by the optional
`tools/extract_protocol.py`, if you want to regenerate the full 74-descriptor
schema or explore commands this toolkit does not implement.

## Verify recording changes against real footage

This camera returns `200 OK` for settings it then ignores. `Options.capture_time_limit`
is the trap: it accepts a write, persists across reconnects, and does nothing.

After changing anything that affects recording, record a clip and check it:

```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 YOUR_CLIP.insv
```

See [docs/FINDINGS.md](docs/FINDINGS.md).

## Docs

| | |
|---|---|
| [PROTOCOL.md](docs/PROTOCOL.md) | The full BLE wire format. Nothing like this was published for the GO 1. |
| [OPTIONS.md](docs/OPTIONS.md) | Every option, and whether this firmware honours it |
| [FINDINGS.md](docs/FINDINGS.md) | Dead ends and traps, so you skip them |

## How this was worked out

The GO 1 predates the protobuf-over-Wi-Fi architecture that every other
Insta360 tool targets — it has no Wi-Fi at all, so none of that work applies.

The protocol came out of `libOne.so` inside the official APK, where all 74
protobuf descriptors are embedded with field names intact, then was verified
command by command against real hardware.

**This repository contains no Insta360 binaries or files extracted from them.**
`tools/extract_protocol.py` regenerates the schema from a copy of the app you
supply yourself.

## Scope

Written for, and tested only on, the **original GO** (firmware v0.4.9.5). Not
GO 2, GO 3, GO 3S or GO Ultra — those have Wi-Fi and are served by
[insta360ctl](https://github.com/xaionaro-go/insta360ctl) and others.

If your GO 1 behaves differently, please
[open a camera report](../../issues/new?template=camera-report.md). Reports of
settings that are accepted but ignored are especially valuable — that is exactly
how the `capture_time_limit` decoy was found.

## Safety

Only settings commands are implemented. There is no firmware-flashing path and
no file deletion. Writes are verified by reading back, and options known to be
ignored are flagged before you write them.

A 20-second button hold factory-resets the camera, which restores recording
length and button mapping to defaults — a way out if you get something wrong.

## Credits

Protocol reverse-engineered and verified against hardware by
**Baraa Fadhloun**, on a GO 1 running firmware v0.4.9.5.

MIT licensed.
