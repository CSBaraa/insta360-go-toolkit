# Option reference

What a GO 1 on firmware v0.4.9.5 actually does. Read `docs/FINDINGS.md` first —
several of these accept writes and ignore them.

Legend: **works** verified end to end · **reads** returns a value, effect
unverified · **decoy** accepts writes, does nothing · **absent** no value

## Camera-wide (`Options`, via `GET/SET_OPTIONS`)

| # | Name | Status | Notes |
|---|---|---|---|
| 7 | `capture_time_limit` | **decoy** | Use `record_duration` instead |
| 11 | `battery_status` | reads | |
| 12 | `local_time` | **works** | Writes fine, never reads back |
| 13 | `time_zone` | **works** | sint32, zigzag-encoded |
| 14 | `mute` | reads | 0/1 |
| 15 | `serial_number` | reads | |
| 17 | `pressOptions` | **works** | Button map |
| 20 | `storage_state` | reads | |
| 23 | `self_timer` | reads | |
| 28 | `log_mode` | reads | |
| 30 | `firmwareRevision` | reads | |
| 35 | `sport_mode_enable` | reads | |
| 41 | `video_sub_mode` | reads | 0 on ours |
| 48 | `camera_type` | reads | `Insta360 Go` |
| 57 | `television_system` | reads | 0 NTSC / 1 PAL |
| 54 | `standby_duration` | absent | Might still be writable — untested |
| 55 | `quick_capture_enable` | absent | Might still be writable — untested |

37 of 71 return values. The rest are for cameras that share this codebase.

## Per capture mode (`PhotographyOptions`, needs a `FunctionMode`)

| # | Name | Status | Notes |
|---|---|---|---|
| 29 | `record_duration` | **works** | The recording length. Enum is `RECORD_DURAION` |
| 2–6 | brightness, contrast, saturation, hue, sharpness | reads | 64 = neutral |
| 13 | `white_balance` | reads | 0 auto, 1 2700K … 5 7500K |
| 14 | `flicker` | reads | 0 auto, 1 60Hz, 2 50Hz |
| 18 | `log_mode_enable` | reads | |
| 21 | `video_exposure_options` | reads | `{program, iso, shutter_speed}` |
| 24 | `video_iso_top_limit` | reads | 0 = uncapped |
| 32 | `bitrate` | absent | Fixed ~36 Mbps |
| 31 | `record_resolution` | absent | 2720×2720 only |
| 33 | `fov_type` | absent | |
| 34 | `flowstate_base_type` | absent | |

## Function modes

```
0 normal      4 slow_motion   7 normal_video   10 interval_video
1 live_stream 5 burst         8 hdr_photo      11 static_timelapse
2 mobile_tl   6 photo         9 hdr_video      12 timeshift
3 interval                                     13 night_photo
```

**Mode 7 (`normal_video`) is the one a button press records in.**

## Button map

Fields 1–5 apply while powered on; 6–10 (`off_*`) are QuickCapture, used while
powered off.

```
1 click        3 triple_click   5 short_press    7 off_double_click   9 off_long_press
2 double_click 4 long_press     6 off_click      8 off_triple_click  10 off_short_press
```

Modes: `0 leave_unchanged, 1 do_nothing, 2 shut_down, 3 take_photo,
4 record_video, 5 self_timer, 6 timelapse, 7 slow_motion, 8 timelapse_video,
9 interval_shooting, 10 interval_video, 11 hdr_photo, 12 static_timelapse,
13 calibrate_gyro`

`7 slow_motion` is capped by `record_duration` for mode 4 — 15 s by default,
and the usual reason clips stop early.
