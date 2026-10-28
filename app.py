"""Unduhin — backend pengunduh media dari YouTube, Instagram, dan TikTok.

Backend FastAPI + yt-dlp:
  POST /api/info            -> metadata + daftar format (video/audio)
  POST /api/prepare         -> mulai tugas unduhan di latar belakang
  GET  /api/task/{id}       -> status & progres tugas
  GET  /api/file/{id}       -> file hasil unduhan (attachment)
  GET  /api/thumbnail?url=  -> proxy gambar pratinjau (menghindari hotlink block)
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

LOCAL_BIN = BASE_DIR / "bin"
if LOCAL_BIN.exists():
    os.environ["PATH"] = f"{LOCAL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"

COOKIES_FILE = BASE_DIR / "cookies.txt"
FFMPEG_OK = shutil.which("ffmpeg") is not None

VIDEO_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240, 144]
QUALITY_BADGE = {2160: "4K", 1440: "2K", 1080: "Full HD", 720: "HD", 480: "SD"}
AUDIO_BITRATES = [320, 256, 192, 128, 64]

PLATFORMS = [
    ("youtube", r"(^|\.)(youtube\.com|youtu\.be)$"),
    ("instagram", r"(^|\.)instagram\.com$"),
    ("tiktok", r"(^|\.)tiktok\.com$"),
]

ERROR_PATTERNS = [
    (r"is ?live|live event", "Siaran langsung belum bisa diunduh."),
    (r"private", "Konten ini privat. Hanya pemilik akun yang dapat mengunduhnya."),
    (r"login|sign in|confirm you|age.?restrict|cookies", "Konten ini meminta login atau verifikasi usia. Simpan cookies browser sebagai cookies.txt di folder aplikasi untuk melewatinya."),
    (r"rate.?limit|too many|429", "Terlalu banyak permintaan dari jaringan ini. Coba lagi beberapa saat."),
    (r"unexpected response|challenge|captcha|bot", "Platform memblokir permintaan dari jaringan ini (deteksi bot). Coba beberapa saat lagi, ganti tautan, atau tambahkan cookies.txt."),
    (r"unsupported", "Tautan tidak dikenali. Gunakan tautan dari YouTube, Instagram, atau TikTok."),
    (r"unavailable|does not exist|removed|terminated|404|not found|no video", "Konten tidak tersedia, telah dihapus, atau tautannya salah."),
    (r"geo|not available in your country", "Konten tidak tersedia untuk wilayah/jaringan ini."),
]


def friendly_error(msg: str) -> str:
    for pattern, text in ERROR_PATTERNS:
        if re.search(pattern, msg, re.I):
            return text
    return "Gagal memproses tautan. Periksa kembali tautan atau coba lagi nanti."


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Tautan masih kosong.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw.lstrip("/")
    return raw


def detect_platform(url: str) -> Optional[str]:
    m = re.match(r"^https?://([^/?#]+)", url, re.I)
    if not m:
        return None
    host = m.group(1).lower().split(":")[0]
    for name, pattern in PLATFORMS:
        if re.search(pattern, host):
            return name
    return None


def human_size(n: int, approx: bool = False) -> str:
    if not n:
        return "?"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            value = f"{size:.1f}".rstrip("0").rstrip(".")
            return ("± " if approx else "") + f"{value} {unit}"
        size /= 1024
    return "?"


def human_duration(seconds: float) -> str:
    s = int(seconds or 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def clean_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name[:120] or "media"


def bitrate_note(br: int) -> str:
    if br >= 256:
        return "Kualitas terbaik"
    if br >= 192:
        return "Seimbang"
    if br >= 128:
        return "Standar"
    return "Hemat kuota"


def ydl_opts(**extra):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 3,
        "nocheckcertificate": True,
        "windowsfilenames": True,
    }
    if COOKIES_FILE.exists():
        opts["cookiefile"] = str(COOKIES_FILE)
    if FFMPEG_OK:
        opts["ffmpeg_location"] = str(Path(shutil.which("ffmpeg")).parent)
    opts.update(extra)
    return opts


def fetch_info(url: str) -> dict:
    try:
        with YoutubeDL(ydl_opts()) as ydl:
            return ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise ValueError(friendly_error(str(exc))) from None


def _is_audio_only(fmt: dict) -> bool:
    return fmt.get("vcodec") == "none" and fmt.get("acodec") not in (None, "none")


def _fmt_bytes(fmt: dict) -> tuple[int, bool]:
    exact = fmt.get("filesize") or 0
    if exact:
        return exact, False
    approx = fmt.get("filesize_approx") or 0
    if approx:
        return approx, True
    return 0, False


def _est_from_bitrate(fmt: dict, duration: float) -> tuple[int, bool]:
    tbr = fmt.get("tbr") or 0
    if tbr and duration:
        return int(tbr * 1000 * duration / 8), True
    return 0, False


def video_options(info: dict, duration: float) -> list[dict]:
    formats = [f for f in (info.get("formats") or []) if f.get("vcodec") not in (None, "none")]
    audio_only = [f for f in formats if _is_audio_only(f)]
    extra_exact = max((_fmt_bytes(f)[0] for f in audio_only), default=0)
    extra_est, _ = max(
        (_est_from_bitrate(f, duration) for f in audio_only),
        default=(0, False), key=lambda t: t[0],
    )
    extra_audio = extra_exact or extra_est

    groups: dict[int, tuple] = {}
    for f in formats:
        h = f.get("height")
        if not h:
            continue
        std = min(VIDEO_HEIGHTS, key=lambda c: abs(c - h))
        score = (
            1 if f.get("acodec") not in (None, "none") else 0,
            1 if f.get("ext") == "mp4" else 0,
            1 if str(f.get("vcodec") or "").startswith("avc1") else 0,
            f.get("tbr") or 0,
        )
        if std not in groups or score > groups[std][0]:
            groups[std] = (score, f)

    options = []
    for std in sorted(groups, reverse=True):
        f = groups[std][1]
        size, approx = _fmt_bytes(f)
        if not size:
            size, approx = _est_from_bitrate(f, duration)
        progressive = f.get("acodec") not in (None, "none")
        if not progressive:
            size += extra_audio
            approx = approx or bool(extra_audio)
        options.append({
            "height": std,
            "label": f"{std}p",
            "badge": QUALITY_BADGE.get(std, ""),
            "fps": int(f.get("fps") or 0),
            "progressive": progressive,
            "size_bytes": int(size),
            "size": human_size(int(size), approx),
        })
    return options


def audio_options(info: dict, duration: float) -> list[dict]:
    formats = info.get("formats") or []
    best_abr = max(
        [f.get("abr") or 0 for f in formats if f.get("acodec") not in (None, "none")],
        default=0,
    )
    ceiling = max(best_abr, 128)
    allowed = [br for br in AUDIO_BITRATES if br <= ceiling] or [AUDIO_BITRATES[-1]]
    options = []
    for br in allowed:
        size_bytes = int(br * 1000 * (duration or 0) / 8)
        options.append({
            "bitrate": br,
            "label": f"{br} kbps",
            "badge": bitrate_note(br),
            "size_bytes": size_bytes,
            "size": human_size(size_bytes),
        })
    return options


TASKS: dict[str, dict] = {}
TASK_TTL = 20 * 60  # file sementara dihapus 20 menit setelah selesai


def _make_hooks(task: dict):
    def progress_hook(d):
        if d["status"] == "downloading":
            task["status"] = "downloading"
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                task["progress"] = max(task["progress"], min(94, int(done * 94 / total)))
        elif d["status"] == "finished":
            task["status"] = "processing"
            task["progress"] = max(task["progress"], 95)

    def pp_hook(d):
        if d.get("status") == "started":
            task["status"] = "processing"
            task["progress"] = max(task["progress"], 95)

    return progress_hook, pp_hook


def run_task(task_id: str, payload: dict):
    task = TASKS[task_id]
    workdir = DOWNLOAD_DIR / task_id
    workdir.mkdir(parents=True, exist_ok=True)
    mode = payload["mode"]
    try:
        if mode == "audio":
            extra = {
                "format": "bestaudio/best",
                "outtmpl": str(workdir / "%(title).100s.%(ext)s"),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(payload.get("bitrate") or 192),
                }],
            }
        else:
            height = payload.get("quality") or 720
            extra = {
                "format": (
                    f"bestvideo[height<={height}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
                    f"bestvideo[height<={height}]+bestaudio/"
                    f"best[height<={height}]/best"
                ),
                "outtmpl": str(workdir / "%(title).100s.%(ext)s"),
                "merge_output_format": "mp4",
                "concurrent_fragment_downloads": 4,
            }
        phook, pp_hook = _make_hooks(task)
        extra["progress_hooks"] = [phook]
        extra["postprocessor_hooks"] = [pp_hook]

        if not FFMPEG_OK:
            raise RuntimeError("FFmpeg belum terpasang. Jalankan setup.bat untuk menambahkannya.")

        with YoutubeDL(ydl_opts(**extra)) as ydl:
            info = ydl.extract_info(payload["url"], download=True)

        title = clean_filename(info.get("title") or "media")
        ext = "mp3" if mode == "audio" else "mp4"
        candidates = [p for p in workdir.iterdir() if p.suffix.lower() == f".{ext}" and p.is_file()]
        if not candidates:
            raise RuntimeError("File hasil tidak ditemukan setelah pemrosesan.")
        src = max(candidates, key=lambda p: p.stat().st_size)
        final = workdir / f"{title}.{ext}"
        if src != final:
            os.replace(src, final)
        task.update(
            status="ready", progress=100, title=title,
            filename=final.name, size_bytes=final.stat().st_size,
            size=human_size(final.stat().st_size), done_at=time.time(),
        )
    except DownloadError as exc:
        task.update(status="error", error=friendly_error(str(exc)), done_at=time.time())
    except Exception as exc:
        task.update(status="error", error=str(exc) or "Terjadi kesalahan tak terduga.", done_at=time.time())


def janitor():
    while True:
        time.sleep(120)
        now = time.time()
        for task_id, task in list(TASKS.items()):
            done_at = task.get("done_at")
            if done_at and now - done_at > TASK_TTL:
                shutil.rmtree(DOWNLOAD_DIR / task_id, ignore_errors=True)
                TASKS.pop(task_id, None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    for path in DOWNLOAD_DIR.iterdir():
        shutil.rmtree(path, ignore_errors=True)
    threading.Thread(target=janitor, daemon=True).start()
    yield


app = FastAPI(title="Unduhin", lifespan=lifespan)


class InfoIn(BaseModel):
    url: str


@app.post("/api/info")
def api_info(body: InfoIn):
    try:
        url = normalize_url(body.url[:2000])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    platform = detect_platform(url)
    if not platform:
        raise HTTPException(status_code=400, detail="Saat ini hanya mendukung tautan YouTube, Instagram, dan TikTok.")
    try:
        info = fetch_info(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if info.get("is_live"):
        raise HTTPException(status_code=400, detail="Siaran langsung belum bisa diunduh.")
    duration = info.get("duration") or 0
    videos = video_options(info, duration)
    if not FFMPEG_OK:
        videos = [v for v in videos if v["progressive"]]
    return {
        "title": info.get("title") or "Tanpa judul",
        "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id") or "",
        "duration": human_duration(duration),
        "duration_seconds": duration,
        "thumbnail": info.get("thumbnail") or "",
        "url": url,
        "platform": platform,
        "videos": videos,
        "audios": audio_options(info, duration),
        "ffmpeg": FFMPEG_OK,
    }


class PrepareIn(BaseModel):
    url: str
    mode: str
    quality: Optional[int] = None
    bitrate: Optional[int] = None


@app.post("/api/prepare")
def api_prepare(body: PrepareIn):
    try:
        url = normalize_url(body.url[:2000])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not detect_platform(url):
        raise HTTPException(status_code=400, detail="Saat ini hanya mendukung tautan YouTube, Instagram, dan TikTok.")
    if body.mode not in ("video", "audio"):
        raise HTTPException(status_code=400, detail="Mode tidak dikenal.")
    if body.mode == "video" and body.quality not in VIDEO_HEIGHTS:
        raise HTTPException(status_code=400, detail="Resolusi tidak tersedia.")
    if body.mode == "audio" and body.bitrate not in AUDIO_BITRATES:
        raise HTTPException(status_code=400, detail="Bitrate tidak tersedia.")
    if not FFMPEG_OK:
        raise HTTPException(status_code=503, detail="FFmpeg belum terpasang. Jalankan setup.bat terlebih dahulu.")

    task_id = uuid.uuid4().hex[:12]
    TASKS[task_id] = {
        "id": task_id, "status": "starting", "progress": 0,
        "error": None, "filename": None, "title": None,
        "size_bytes": 0, "size": "?", "mode": body.mode,
        "quality": body.quality, "bitrate": body.bitrate,
        "created": time.time(), "done_at": None,
    }
    threading.Thread(target=run_task, args=(task_id, body.model_dump()), daemon=True).start()
    return {"task_id": task_id}


@app.get("/api/task/{task_id}")
def api_task(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan atau telah kedaluwarsa.")
    return {
        "id": task["id"], "status": task["status"], "progress": task["progress"],
        "error": task["error"], "title": task["title"], "filename": task["filename"],
        "size": task["size"], "size_bytes": task["size_bytes"], "mode": task["mode"],
        "quality": task["quality"], "bitrate": task["bitrate"],
    }


@app.get("/api/file/{task_id}")
def api_file(task_id: str):
    task = TASKS.get(task_id)
    if not task or task["status"] != "ready" or not task.get("filename"):
        raise HTTPException(status_code=404, detail="File tidak tersedia. Analisis ulang tautan, lalu unduh kembali.")
    path = DOWNLOAD_DIR / task_id / task["filename"]
    if not path.exists():
        raise HTTPException(status_code=410, detail="File telah dihapus dari server (masa simpan 20 menit). Silakan unduh ulang.")
    media = "audio/mpeg" if task["mode"] == "audio" else "video/mp4"
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/api/thumbnail")
def api_thumbnail(url: str):
    if not re.match(r"^https?://", url, re.I):
        raise HTTPException(status_code=400, detail="URL thumbnail tidak valid.")
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "image/jpeg")
        if not ctype.startswith("image/"):
            raise ValueError
        return Response(content=resp.content, media_type=ctype)
    except Exception:
        raise HTTPException(status_code=502, detail="Gagal memuat gambar pratinjau.")


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
