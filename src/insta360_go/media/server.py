"""Local web app for browsing, previewing and exporting camera footage."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .discover import Clip, by_name, find_clips, media_roots
from .export import (
    Settings,
    audio_args,
    codec_args,
    effective_duration,
    run_ffmpeg,
    software_fallback,
    video_filters,
)

OUT_DIR = Path.home() / "Desktop" / "insta360-go"
CACHE = Path(__import__("os").environ.get("TMPDIR", "/tmp")) / "insta360-go-cache"
PAGE = (Path(__file__).parent / "page.html").read_text()

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_cancel = threading.Event()


def _set_job(name: str, state: str, msg: str, pct: float = 0) -> None:
    with _lock:
        _jobs[name] = {"state": state, "msg": msg, "pct": int(pct)}


def _cache_name(name: str, suffix: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / (re.sub(r"\W+", "_", name) + suffix)


def thumbnail(clip: Clip) -> Path | None:
    dest = _cache_name(clip.name, ".jpg")
    if dest.exists() and dest.stat().st_size:
        return dest
    seek = ["-ss", "1"] if (clip.duration or 0) > 2 else []
    subprocess.run(["ffmpeg", "-y", "-v", "error", *seek, "-i", clip.path,
                    "-frames:v", "1", "-vf", "scale=560:-2", str(dest)],
                   capture_output=True, timeout=60)
    return dest if dest.exists() else None


def playable(clip: Clip) -> Path | None:
    """Remux to browser-playable mp4. Lossless; .insv is already H.264."""
    dest = _cache_name(clip.name, ".mp4")
    if dest.exists() and dest.stat().st_size:
        return dest
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip.path, "-c", "copy",
                        "-movflags", "+faststart", str(dest)],
                       capture_output=True, timeout=900)
    return dest if r.returncode == 0 and dest.exists() else None


def sample(name: str, s: Settings) -> Path | None:
    """Render a 3-second sample so settings can be checked before a batch."""
    clip = by_name(name)
    if clip is None:
        return None
    key = hashlib.md5((name + json.dumps(s.__dict__, sort_keys=True, default=str)
                       ).encode()).hexdigest()[:16]
    dest = CACHE / f"prev_{key}.mp4"
    CACHE.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size:
        return dest
    duration = clip.duration or 3
    preview = Settings(**{**s.__dict__, "stab": "fast" if s.stab != "off" else "off"})
    if preview.trim_start is None and preview.trim_end is None:
        preview.trim_start = max(0, duration / 2 - 1.5)
    preview.trim_end = min(duration, (preview.trim_start or 0) + 3)
    vf = video_filters(clip, preview)
    args = ["-y", "-v", "error", "-i", clip.path] + (["-vf", vf] if vf else []) + [
        "-c:v", "h264_videotoolbox", "-b:v", "12M", "-allow_sw", "1",
        "-pix_fmt", "yuv420p", *audio_args(preview),
        "-movflags", "+faststart", str(dest)]
    if subprocess.run(["ffmpeg", *args], capture_output=True, timeout=300).returncode:
        return None
    return dest


def export_clip(name: str, s: Settings) -> None:
    clip = by_name(name)
    if clip is None:
        return _set_job(name, "error", "not found on the camera")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if clip.kind == "photo":
            _set_job(name, "working", "copying", 40)
            shutil.copy2(clip.path, OUT_DIR / clip.name)
            return _set_job(name, "done", "copied", 100)
        if s.keep_original:
            _set_job(name, "working", "copying original", 3)
            shutil.copy2(clip.path, OUT_DIR / clip.name)

        dest = OUT_DIR / (Path(clip.name).stem + ".mp4")
        if s.mode == "copy":
            _set_job(name, "working", "remuxing", 20)
            run_ffmpeg(["-i", clip.path, "-c", "copy", "-movflags", "+faststart",
                        str(dest)],
                       lambda f: _set_job(name, "working", "remuxing", 20 + 78 * f),
                       clip.duration or 1)
            return _set_job(name, "done", "imported", 100)

        trf = None
        base = 5.0
        if s.stab == "best":
            trf = str(_cache_name(name, ".trf"))
            pre = video_filters(clip, Settings(**{**s.__dict__, "stab": "off",
                                                  "aspect": "source", "res": "source"}))
            detect = (pre + "," if pre else "") + \
                f"vidstabdetect=shakiness=8:accuracy=15:result={trf}"
            _set_job(name, "working", "analyzing motion (1/2)", 5)
            run_ffmpeg(["-i", clip.path, "-vf", detect, "-f", "null", "-"],
                       lambda f: _set_job(name, "working", "analyzing motion (1/2)",
                                          5 + 35 * f), clip.duration or 1)
            base = 40.0

        vf = video_filters(clip, s, trf)
        total = effective_duration(clip, s)
        def report(f):
            return _set_job(name, "working", "encoding", base + (99 - base) * f)
        args = ["-i", clip.path] + (["-vf", vf] if vf else []) + \
            codec_args(clip, s) + audio_args(s) + ["-movflags", "+faststart", str(dest)]
        if run_ffmpeg(args, report, total) == "vt_failed":
            args = ["-i", clip.path] + (["-vf", vf] if vf else []) + \
                software_fallback(s) + audio_args(s) + \
                ["-movflags", "+faststart", str(dest)]
            run_ffmpeg(args, report, total)
        _set_job(name, "done", "exported", 100)
    except Exception as exc:
        _set_job(name, "error", str(exc)[:240])


def _run_batch(names, s: Settings) -> None:
    _cancel.clear()
    for n in names:
        _set_job(n, "queued", "waiting")
    for n in names:
        if _cancel.is_set():
            _set_job(n, "error", "cancelled")
            continue
        export_clip(n, s)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _file(self, path: Path, ctype: str):
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                code = 206
        length = max(0, end - start + 1)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        name = unquote(query.get("name", [""])[0])
        if url.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if url.path == "/api/clips":
            return self._send(200, json.dumps({
                "outDir": str(OUT_DIR), "roots": media_roots(),
                "clips": [c.as_dict() | {"imported": (OUT_DIR / (Path(c.name).stem + ".mp4")).exists()}
                          for c in find_clips()]}))
        if url.path == "/api/jobs":
            with _lock:
                return self._send(200, json.dumps(_jobs))
        if url.path == "/thumb":
            clip = by_name(name)
            path = thumbnail(clip) if clip else None
            return self._file(path, "image/jpeg") if path else self._send(404, b"{}")
        if url.path == "/stream":
            clip = by_name(name)
            if clip is None:
                return self._send(404, b"{}")
            if clip.kind == "photo":
                return self._file(Path(clip.path), "image/jpeg")
            path = playable(clip)
            return self._file(path, "video/mp4") if path else self._send(415, b"{}")
        if url.path == "/preview":
            s = Settings.from_dict(json.loads(unquote(query.get("s", ["{}"])[0])))
            path = sample(name, s)
            return self._file(path, "video/mp4") if path else self._send(500, b"{}")
        if url.path == "/api/reveal":
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(OUT_DIR)])
            return self._send(200, b'{"ok":true}')
        return self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or "{}")
        if url.path == "/api/export":
            raw = body.get("settings") or {}
            raw.setdefault("trim_start", raw.pop("trimStart", None))
            raw.setdefault("trim_end", raw.pop("trimEnd", None))
            raw.setdefault("keep_original", raw.pop("keepOriginal", True))
            threading.Thread(target=_run_batch,
                             args=(body.get("names") or [], Settings.from_dict(raw)),
                             daemon=True).start()
            return self._send(200, b'{"ok":true}')
        if url.path == "/api/cancel":
            _cancel.set()
            return self._send(200, b'{"ok":true}')
        return self._send(404, b'{"error":"not found"}')


def serve(port: int = 8731, open_browser: bool = True) -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not found on PATH. Install it (brew install ffmpeg).")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise SystemExit(
            f"port {port} is busy ({exc}). Try: go1 export --port 8732") from exc
    print(f"footage browser  ->  http://localhost:{port}")
    print(f"exports go to    ->  {OUT_DIR}")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
