# Findings, dead ends and traps

Written so nobody has to rediscover any of this. Every entry cost real time.

---

## 1. `capture_time_limit` is a decoy

`Options.capture_time_limit` (option 7) is the obvious candidate for recording
length. On a GO 1 it:

- accepts a write and returns **200**
- **persists** — reads back correctly across reconnects
- has **no effect whatsoever** on how long the camera records

We set it to 60, confirmed 60 on a fresh connection, recorded a clip, and got
15.16 s. It reads `0` from the factory, which matches nothing.

**The real field is `PhotographyOptions.record_duration`**, addressed per
`FunctionMode` — see below.

> A `200` from this camera means "message understood", not "setting applied".
> Verify recording-related changes against actual footage, always.

## 2. `RECORD_DURAION` — the typo that hides it

Insta360 misspelled their own enum:

```
PhotographyOptionType.RECORD_DURAION = 29     (not RECORD_DURATION)
```

Grepping the binary for `RECORD_DURATION` finds nothing. The struct field is
spelled correctly (`record_duration`); only the enum is wrong.

## 3. Recording length is per capture mode

There is no single global duration. Each `FunctionMode` has its own:

```
mode  4 slow_motion      15      <- firmware default for slow-mo
mode  7 normal_video     15      <- what a button press uses
mode 10 interval_video   15
every other mode         30      <- untouched factory default
```

`normal_video` is the one that matters — it is the mode a button press records
in. Everything sitting at 30 is simply factory default.

## 4. "Reads empty" does not mean "cannot be written"

34 of 71 `Options` return nothing on read. It is tempting to call them
unsupported. **`local_time` reads empty and writes fine** — we set the clock
and filenames went from `VID_20200904_...` to `VID_20260910_...`.

So a read returning nothing tells you only that the getter is unimplemented.
Untested-but-plausible writes include `quick_capture_enable`, `standby_duration`
and `over_heat_protection`.

## 5. Genuinely absent on GO 1

These return nothing *and* have no observable effect:

| Option | Consequence |
|---|---|
| `PHOTO_GRAPHY_BITRATE` (32) | Bitrate is fixed at ~36 Mbps. Not adjustable. |
| `RECORD_RESOLUTION` (31) | 2720×2720 only. |
| `FOV_TYPE` (33) | No in-camera field-of-view control. |
| `FLOWSTATE_BASE_TYPE` (34) | No in-camera stabilization toggle. |
| `video_encode_type` | H.264 only, no H.265. |

`Options.video_bitrate` reads **60** while the camera actually produces
**36 Mbps**. Another decoy — and unlike duration there is no working
equivalent behind it.

## 6. The camera lies about its own clock

Its RTC resets to 2020. Files come off the card dated 2020 regardless of when
they were shot, which makes "is this clip new?" genuinely hard during testing.
Fix it with `go1 clock` before any experiment where file age matters. Neither
`local_time` nor `time_zone` reads back, so the only confirmation is the date
on the next recording.

## 7. Button mapping has no duration

`ButtonPressOptions` maps press gestures to `ButtonPressMode` and nothing else.
The 15-second slow-mo cap comes from `record_duration` for
`FunctionMode.HIGH_FRAME_RATE`, not from the button.

Fields prefixed `shutdown_` are the **QuickCapture** actions — what the button
does while the camera is powered off.

## 8. Things that will waste your time

- **The GO 1 has no Wi-Fi.** Every mature Insta360 tool speaks protobuf over
  TCP `192.168.42.1:6666`. None of it is portable here.
- **The camera sleeps quickly.** It stops advertising; scans return nothing.
  Power it on immediately before running anything.
- **It drops off USB on its own.** Clean the pogo pins before long transfers.
- **The FAT32 directory can read partially.** An early scan found 6 clips where
  28 existed. Re-mount before trusting a file listing.
- **macOS kills sandboxed Bluetooth.** A process without Bluetooth permission
  dies with SIGABRT (exit 134) the instant it touches CoreBluetooth. Run from a
  terminal that has been granted access.

## 9. Method that worked

1. Get the official APK (Insta360's own CDN still serves v1.3.4).
2. Verify its signature — ours is `CN=Insta360`, self-signed, valid to 2044.
3. The protocol is **not** in the Java. `nativeGetOptions` means it lives in
   `libOne.so`, and the protobuf descriptors are embedded there in full, field
   names intact.
4. Recover descriptors by scanning for `\x0A<len><name>.proto` and parsing —
   taking the **longest** valid parse, not the first.
5. Confirm every value against hardware. Then confirm recording changes against
   actual footage, because step 5 is where `capture_time_limit` fools you.
