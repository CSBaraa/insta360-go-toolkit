"""Convert .insv footage with ffmpeg.

An .insv is a QuickTime container holding ordinary H.264, so a lossless remux
to .mp4 needs no re-encoding. Keep the original if you may ever want Insta360
Studio's gyro-based FlowState stabilization -- only it can read that data.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from typing import Callable

ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3, "21:9": 21 / 9}
BITRATE_BASE = {2160: 60, 1440: 32, 1080: 18, 720: 9}
QUALITY_SCALE = {"high": 1.0, "medium": 0.55, "small": 0.3}
CRF = {"high": 18, "medium": 22, "small": 26}


@dataclass
class Settings:
    mode: str = "copy"            # copy | encode
    aspect: str = "16:9"
    zoom: float = 1.0
    panx: float = 0.0
    pany: float = 0.0
    rotate: float = 0.0
    defish: int = 0
    stab: str = "off"             # off | fast | best
    res: str = "source"
    fps: str = "source"
    speed: float = 1.0
    codec: str = "h264_hw"
    quality: str = "high"
    bright: int = 0
    contrast: int = 100
    sat: int = 100
    sharpen: int = 0
    trim_start: float | None = None
    trim_end: float | None = None
    keep_original: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> Settings:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def crop_rect(width: int, height: int, s: Settings):
    """Largest rect of the chosen aspect inside the frame, shrunk and panned.

    The GO shoots square, so cropping is how you choose the shot -- nothing is
    upscaled until zoom passes roughly 1.5x.
    """
    aspect = ASPECTS.get(s.aspect)
    if aspect is None:
        return None
    if width / height >= aspect:
        cw, ch = height * aspect, height
    else:
        cw, ch = width, width / aspect
    zoom = max(1.0, s.zoom)
    cw, ch = min(cw / zoom, width), min(ch / zoom, height)
    x = (width - cw) / 2 + s.panx * (width - cw) / 2
    y = (height - ch) / 2 + s.pany * (height - ch) / 2
    def even(v):
        return int(v) // 2 * 2
    return even(cw), even(ch), even(max(0, min(x, width - cw))), even(max(0, min(y, height - ch)))


def _trim_range(s: Settings) -> str | None:
    if s.trim_start is None and s.trim_end is None:
        return None
    parts = []
    if s.trim_start is not None:
        parts.append(f"start={float(s.trim_start)}")
    if s.trim_end is not None:
        parts.append(f"end={float(s.trim_end)}")
    return ":".join(parts)


def video_filters(clip, s: Settings, trf: str | None = None) -> str | None:
    width = clip.width or 2720
    height = clip.height or 2720
    chain: list[str] = []

    # Trim as a filter, not -ss/-t: it stays frame-exact and composes correctly
    # with a speed change, which output-side seeking does not.
    trim = _trim_range(s)
    if trim:
        chain += [f"trim={trim}", "setpts=PTS-STARTPTS"]

    if s.stab == "best" and trf:
        chain.append(f"vidstabtransform=input={trf}:smoothing=24:optzoom=1:interpol=bicubic")
    elif s.stab == "fast":
        chain.append("deshake=rx=32:ry=32")
    if abs(s.rotate) > 0.01:
        chain.append(f"rotate={math.radians(s.rotate)}:ow=iw:oh=ih:fillcolor=black")
    if s.defish > 0:
        k = s.defish / 100.0
        chain.append(f"lenscorrection=k1={-0.22 * k:.4f}:k2={-0.022 * k:.4f}")

    rect = crop_rect(width, height, s)
    if rect:
        cw, ch, cx, cy = rect
        chain.append(f"crop={cw}:{ch}:{cx}:{cy}")
        out_w, out_h = cw, ch
    else:
        out_w, out_h = width, height

    if s.res != "source":
        target = int(s.res)
        # never upscale past the source
        if out_h > out_w:
            if target < out_w:
                chain.append(f"scale={target}:-2")
        elif target < out_h:
            chain.append(f"scale=-2:{target}")

    eq = []
    if s.bright:
        eq.append(f"brightness={s.bright / 100:.3f}")
    if s.contrast != 100:
        eq.append(f"contrast={s.contrast / 100:.3f}")
    if s.sat != 100:
        eq.append(f"saturation={s.sat / 100:.3f}")
    if eq:
        chain.append("eq=" + ":".join(eq))
    if s.sharpen:
        chain.append(f"unsharp=5:5:{s.sharpen / 100 * 1.5:.2f}")
    if s.fps != "source":
        chain.append(f"fps={int(s.fps)}")
    if abs(s.speed - 1.0) > 0.001:
        chain.append(f"setpts=PTS/{s.speed}")
    return ",".join(chain) if chain else None


def audio_args(s: Settings) -> list[str]:
    chain: list[str] = []
    trim = _trim_range(s)
    if trim:
        chain += [f"atrim={trim}", "asetpts=PTS-STARTPTS"]
    if abs(s.speed - 1.0) >= 0.001:
        if s.speed <= 0.25:
            return ["-an"]                     # beyond what atempo can chain
        rem = s.speed
        while rem > 2.0:
            chain.append("atempo=2.0")
            rem /= 2.0
        while rem < 0.5:
            chain.append("atempo=0.5")
            rem /= 0.5
        chain.append(f"atempo={rem:.4f}")
    if not chain:
        return ["-c:a", "aac", "-b:a", "192k"]
    return ["-filter:a", ",".join(chain), "-c:a", "aac", "-b:a", "192k"]


def codec_args(clip, s: Settings) -> list[str]:
    res = int(s.res) if s.res != "source" else (clip.height or 1080)
    base = BITRATE_BASE.get(res, 24)
    mbit = max(4, base * QUALITY_SCALE[s.quality] * max(1.0, s.speed) ** 0.5)
    if s.codec == "h264_x264":
        return ["-c:v", "libx264", "-preset", "medium",
                "-crf", str(CRF[s.quality]), "-pix_fmt", "yuv420p"]
    enc = "hevc_videotoolbox" if s.codec == "h265_hw" else "h264_videotoolbox"
    # allow_sw: VideoToolbox refuses some dimensions outright (error -12908)
    args = ["-c:v", enc, "-b:v", f"{mbit:.0f}M", "-allow_sw", "1", "-pix_fmt", "yuv420p"]
    return args + (["-tag:v", "hvc1"] if enc.startswith("hevc") else [])


def software_fallback(s: Settings) -> list[str]:
    enc = "libx265" if s.codec == "h265_hw" else "libx264"
    args = ["-c:v", enc, "-preset", "medium", "-crf", str(CRF[s.quality]),
            "-pix_fmt", "yuv420p"]
    return args + (["-tag:v", "hvc1"] if enc == "libx265" else [])


def effective_duration(clip, s: Settings) -> float:
    total = clip.duration or 0
    start = s.trim_start or 0
    end = s.trim_end if s.trim_end is not None else total
    return max(0.1, (end - start) / max(0.01, s.speed))


def run_ffmpeg(args: list[str], on_progress: Callable[[float], None] | None = None,
               total: float = 1.0) -> object:
    """Run ffmpeg. Returns True, False, or 'vt_failed' when VideoToolbox refused."""
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if line.startswith("out_time_us=") and on_progress:
            try:
                on_progress(min(1.0, int(line.split("=")[1]) / 1e6 / max(0.1, total)))
            except ValueError:
                pass
    proc.wait()
    if proc.returncode != 0:
        err = (proc.stderr.read() or "").strip()
        if "compression session" in err or "allow_sw" in err:
            return "vt_failed"
        raise RuntimeError(err[:300] or "ffmpeg failed")
    return True
