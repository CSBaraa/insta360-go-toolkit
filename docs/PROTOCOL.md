# Insta360 GO (1st generation) BLE protocol

Reverse-engineered from `libOne.so` inside the official Insta360 GO app v1.3.4,
then verified command by command against real hardware (firmware **v0.4.9.5**).

Everything here was confirmed by round-tripping against a camera. Where a claim
is untested it says so.

---

## Transport

The camera advertises as `GO <serial-suffix>` — e.g. serial `IGS0000XXXXXXX`
advertises as `GO XXXXXX` — with service UUID `0000be80`.

| | UUID | Direction |
|---|---|---|
| Service | `0000be80-0000-1000-8000-00805f9b34fb` | |
| Write | `0000be81-...` | app → camera |
| Notify | `0000be82-...` | camera → app |
| Read | `0000be83-...` | returns `11223344` — a placeholder, no known use |

The GO 1 has **no Wi-Fi**. BLE and the wired charge case are the only paths in,
which is why Wi-Fi-based tooling for other Insta360 cameras cannot be ported.

Observed MTU: 515. Replies still arrive split across notifications, so a
reassembly buffer is mandatory.

---

## Frame format

A 16-byte header followed by a protobuf body.

```
offset  size  field
0       2     TOTAL length, little-endian   <-- header + payload
2       2     reserved (0)
4       1     mode: 0x04 = message
5       2     reserved (0)
7       2     command code; on replies, an HTTP-like status
9       1     content type: 0x02 = protobuf
10      1     sequence number, 1..254 (echoed in the reply)
11      2     reserved (0)
13      1     flags; bit 7 = last fragment
14      2     reserved
```

### The length field is the whole trick

Published notes on newer Insta360 cameras describe offset 0 as the **payload**
length. On the GO 1 that is wrong, and the failure is silent and misleading:

```
payload length (4)  -> 0400000004000008000201000080000008070837
                    <- 07000000050000                    7-byte reject
total length  (20)  -> 1400000004000008000201000080000008070837
                    <- 16000000040000c800...              200 OK
```

Two bytes apart. A payload-length frame gets a short frame back that decodes to
nothing, which reads exactly like "this camera does not speak the protocol".
That single difference is why the GO 1 looked closed.

### Two kinds of traffic that are not replies

**Idle frame.** While idle the camera repeatedly emits:

```
07000000050000
```

Seven bytes, mode `0x05`. Not a response. Discard it.

**Async notifications.** Status values **≥ 8192** are unsolicited events
(`CAMERA_NOTIFICATION_*` — capture state, auto-split, battery). They arrive
whenever the camera feels like it, including between your request and its
reply. A reader that takes the first frame it sees will eventually attribute
one of these to the wrong command.

Because both exist, a length alone is not enough to resynchronise a corrupted
stream — a stray byte can produce a plausible-looking length. Validate
`data[4] == 0x04 && data[9] == 0x02` as a signature before trusting a length.

### Status codes

| Code | Meaning |
|---|---|
| 200 | OK |
| 400 | bad request |
| 500 | execution failed |
| 501 | not implemented |
| ≥ 8192 | asynchronous notification, not a reply |

---

## Commands

Verified on GO 1:

| Code | Command |
|---|---|
| 4 | `START_CAPTURE` |
| 5 | `STOP_CAPTURE` |
| 7 | `SET_OPTIONS` |
| 8 | `GET_OPTIONS` |
| 9 | `SET_PHOTOGRAPHY_OPTIONS` |
| 10 | `GET_PHOTOGRAPHY_OPTIONS` |

The recovered schema lists many more (timelapse, file transfer, live stream,
authorization). Those are **untested here**.

---

## Messages

```protobuf
message GetOptions           { repeated OptionType option_types = 1; }
message SetOptions           { repeated OptionType option_types = 1;
                               Options value = 2; }

message GetPhotographyOptions { PhotographyOptionType option_types = 1;
                                FunctionMode function_mode = 2; }
message SetPhotographyOptions { PhotographyOptionType option_types = 1;
                                PhotographyOptions value = 2;
                                FunctionMode function_mode = 3; }
```

In both option enums, **the enum value equals the field number** in the
corresponding message. `CAPTURE_TIME_LIMIT = 7` selects `Options.capture_time_limit`,
field 7. That symmetry makes the whole surface guessable once you have either half.

### Worked example — read the recording length

```
GetPhotographyOptions{ option_types: 29, function_mode: 7 }
payload  08 1D 10 07
frame    19000000 04 0000 0A00 02 01 0000 80 0000  08 1D 10 07
```

Reply payload `08 1D 12 03 E8 01 3C` decodes as
`{ option_types: 29, value: { record_duration: 60 } }`.

### Worked example — set it

```
SetPhotographyOptions{ option_types: 29,
                       value: { record_duration: 60 },
                       function_mode: 7 }
payload  08 1D 12 03 E8 01 3C 18 07
```

`E8 01` is the key for field 29, wire type 0 — `(29 << 3) | 0 = 232`.

---

## Authorization

The schema contains `check_authorization.proto`, `authorization_result.proto`
and `cancel_authorization.proto`, and `Options` carries an `authorization_id`
field (38, empty on our camera).

**No handshake was needed.** Every command above was accepted on a bare BLE
connection with no prior authorization. Whether that holds for capture control
or file transfer is untested.

---

## Regenerating the schema

`tools/extract_protocol.py` recovers all 74 embedded `FileDescriptorProto`
blobs from `libOne.so` inside an official APK. This repository ships **no**
Insta360 binaries or files extracted from them — supply your own copy.

The one non-obvious detail: scan for the longest parse, not the first. A
truncated descriptor often still parses cleanly, so stopping at the first
success silently loses fields. `OptionType` sits past the truncation point in
`options.proto`, and taking the first valid parse hides it completely.
