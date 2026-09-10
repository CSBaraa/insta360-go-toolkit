"""Find footage on a mounted camera volume and read its properties."""
from __future__ import annotations

import glob
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXT = {".insv", ".mp4", ".mov"}
PHOTO_EXT = {".insp", ".jpg", ".jpeg", ".dng"}

_probe_cache: dict[str, dict] = {}


@dataclass
class Clip:
    name: str
    path: str
    volume: str
    kind: str
    size: int
    mtime: float
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None

    def as_dict(self) -> dict:
        return {**self.__dict__}


def media_roots() -> list[str]:
    """DCIM directories on mounted volumes that actually contain footage."""
    roots = []
    for dcim in sorted(glob.glob("/Volumes/*/DCIM")):
        for _root, _dirs, files in os.walk(dcim):
            if any(Path(f).suffix.lower() in VIDEO_EXT | PHOTO_EXT for f in files):
                roots.append(dcim)
                break
    return roots


def probe(path: str) -> dict:
    if path in _probe_cache:
        return _probe_cache[path]
    info = {"duration": None, "width": None, "height": None, "fps": None}
    try:
        raw = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-show_entries", "stream=width,height,codec_type,r_frame_rate",
             "-of", "json", path],
            capture_output=True, text=True, timeout=20).stdout
        data = json.loads(raw or "{}")
        if data.get("format", {}).get("duration"):
            info["duration"] = float(data["format"]["duration"])
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width")
                info["height"] = stream.get("height")
                num, den = (stream.get("r_frame_rate") or "0/0").split("/")
                if float(den):
                    info["fps"] = round(float(num) / float(den), 2)
                break
    except Exception:
        pass
    _probe_cache[path] = info
    return info


def find_clips() -> list[Clip]:
    clips: list[Clip] = []
    for dcim in media_roots():
        volume = Path(dcim).parent.name
        for root, _dirs, files in os.walk(dcim):
            for name in sorted(files):
                if name.startswith("."):
                    continue
                ext = Path(name).suffix.lower()
                if ext not in VIDEO_EXT | PHOTO_EXT:
                    continue
                path = Path(root) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                clips.append(Clip(
                    name=name, path=str(path), volume=volume,
                    kind="photo" if ext in PHOTO_EXT else "video",
                    size=stat.st_size, mtime=stat.st_mtime, **probe(str(path))))
    clips.sort(key=lambda c: c.mtime)
    return clips


def by_name(name: str) -> Clip | None:
    for clip in find_clips():
        if clip.name == name:
            return clip
    return None
