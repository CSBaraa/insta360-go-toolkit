---
name: Camera report
about: Tell us what your camera does — especially if it differs from ours
title: "[camera] "
labels: camera-report
---

**Camera model and firmware**
Run `go1 info` and paste the output.

**What you tried**
The exact command.

**What happened**
Paste the output. If a setting was accepted but had no effect, say so — that is
the single most useful thing you can report, and it is how `capture_time_limit`
was found to be a decoy.

**Did you verify with real footage?**
For anything affecting recording, please check an actual clip:
`ffprobe -v error -show_entries format=duration -of csv=p=0 YOUR_CLIP.insv`
The camera reports settings it does not act on, so a 200 response proves nothing.
