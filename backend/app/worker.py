"""Background worker for walkthrough videos (docs/SCOPE.md 8.7, 9.4).

Run with `python -m app.worker`. Claims one job at a time from Postgres (SKIP LOCKED, so several
workers can run side by side), then does all reads and writes inside that job's workspace context,
exactly like a request: RLS still applies.

Pipeline: probe → quality check → stabilise (vidstab, two passes) → drop duplicate frames
(mpdecimate, removes pauses) → sample evenly → WebP frame sets (large for desktop, small for phones).
"""

import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

from app import email
from app.db import tenant_session
from app.exports import run_exports
from app.media import frame_key
from app.storage import get_storage

log = logging.getLogger("scrollwalk.worker")

FRAME_COUNT = 240
LONG_EDGE = {"large": 1920, "small": 1280}
MAX_ATTEMPTS = 3
MIN_SECONDS = 6
MIN_SHORT_EDGE = 1080
DARK_LUMA = 50


class VideoRejected(Exception):
    """A problem with the video itself; retrying won't help."""


@dataclass
class Probe:
    width: int
    height: int
    duration: float
    frames: int


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-800:]}")
    return result.stdout + result.stderr


def probe(path: Path) -> Probe:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,nb_frames,avg_frame_rate:stream_side_data=rotation:format=duration", "-of", "json",
         str(path)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        data = json.loads(out.stdout)
        stream = data["streams"][0]
    except (ValueError, KeyError, IndexError):
        raise VideoRejected("We couldn't read that video. Try exporting it again as MP4.") from None
    width, height = int(stream["width"]), int(stream["height"])
    rotation = next((abs(int(d.get("rotation", 0))) for d in stream.get("side_data_list", [])), 0)
    if rotation in (90, 270):
        width, height = height, width
    duration = float(data.get("format", {}).get("duration") or 0)
    num, _, den = stream.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0
    frames = int(stream.get("nb_frames") or 0) or int(duration * fps)
    return Probe(width, height, duration, frames)


def average_luma(path: Path, cwd: Path) -> float:
    out = _run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "fps=1,scale=320:-2,signalstats,"
                "metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"], cwd)
    values = [float(line.rsplit("=", 1)[1]) for line in out.splitlines() if "lavfi.signalstats.YAVG=" in line]
    return sum(values) / len(values) if values else 255.0


def quality_warnings(info: Probe, luma: float) -> list[str]:
    found = []
    if info.duration < MIN_SECONDS:
        found.append("too_short")
    if min(info.width, info.height) < MIN_SHORT_EDGE:
        found.append("low_resolution")
    if luma < DARK_LUMA:
        found.append("too_dark")
    return found


def make_frames(source: Path, work: Path, aspect: str) -> tuple[int, dict]:
    """Writes large/0001.webp… and small/0001.webp… under `work`; returns the count and sizes."""
    _run(["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-vf",
          "vidstabdetect=shakiness=6:accuracy=15:result=motion.trf", "-f", "null", "-"], work)
    _run(["ffmpeg", "-hide_banner", "-y", "-i", str(source), "-an", "-vf",
          "vidstabtransform=input=motion.trf:smoothing=30:zoom=3:optzoom=0,unsharp=5:5:0.5:3:3:0,"
          "mpdecimate,setpts=N/FRAME_RATE/TB",
          "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p", "steady.mp4"], work)
    steady = probe(work / "steady.mp4")
    count = max(1, min(FRAME_COUNT, steady.frames))
    rate = count / steady.duration if steady.duration > 0 else 25
    sizes = {}
    for name, edge in LONG_EDGE.items():
        (work / name).mkdir()
        scale = (f"scale='min({edge},iw)':-2" if aspect == "landscape" else f"scale=-2:'min({edge},ih)'")
        _run(["ffmpeg", "-hide_banner", "-y", "-i", "steady.mp4", "-vf", f"fps={rate:.6f},{scale}",
              "-frames:v", str(count), "-c:v", "libwebp", "-quality", "80" if name == "large" else "76",
              "-compression_level", "4", f"{name}/%04d.webp"], work)
    produced = min(len(list((work / n).glob("*.webp"))) for n in LONG_EDGE)
    if produced == 0:
        raise VideoRejected("We couldn't find usable frames in that video.")
    from PIL import Image

    for name in LONG_EDGE:
        with Image.open(work / name / "0001.webp") as im:
            sizes[name] = {"width": im.width, "height": im.height}
    return produced, sizes


def process(job_id: UUID, workspace_id: UUID, media_id: UUID) -> None:
    storage = get_storage()
    with tenant_session(None, workspace_id) as s:
        video = s.execute(text("SELECT * FROM media WHERE id = :id"), {"id": media_id}).first()
    if video is None or video.deleted_at is not None:
        return
    started = time.monotonic()
    work = Path(tempfile.mkdtemp(prefix="sw-video-"))
    try:
        source = work / ("source" + Path(video.key).suffix)
        storage.download(video.key, source)
        info = probe(source)
        orientation = "landscape" if info.width >= info.height else "portrait"
        if orientation != video.aspect:
            raise VideoRejected(f"This video is {orientation}, but it was uploaded as the {video.aspect} walkthrough.")
        warnings = quality_warnings(info, average_luma(source, work))
        count, sizes = make_frames(source, work, video.aspect)

        frames_id = uuid4()
        prefix = f"private/ws/{workspace_id}/seq/{frames_id}"
        for name in LONG_EDGE:
            for n in range(1, count + 1):
                storage.upload_file(work / name / f"{n:04d}.webp", frame_key(prefix, name, n), "image/webp")

        with tenant_session(video.created_by, workspace_id) as s:
            current = s.execute(text("SELECT deleted_at FROM media WHERE id = :id"), {"id": media_id}).scalar_one()
            if current is not None:
                storage.delete_prefix(prefix + "/")
                return
            s.execute(
                text("""INSERT INTO media (id, workspace_id, listing_id, parent_id, kind, aspect, status, key,
                                           variants, created_by)
                        VALUES (:id, :w, :l, :p, 'frames', :a, 'ready', :key, CAST(:v AS jsonb), :u)"""),
                {"id": frames_id, "w": workspace_id, "l": video.listing_id, "p": media_id, "a": video.aspect,
                 "key": prefix, "v": json.dumps({"count": count, **sizes}), "u": video.created_by},
            )
            s.execute(
                text("""UPDATE media SET status = 'ready', width = :w, height = :h, duration_ms = :d,
                               warnings = CAST(:warn AS jsonb), error = NULL, updated_at = now() WHERE id = :id"""),
                {"w": info.width, "h": info.height, "d": int(info.duration * 1000), "warn": json.dumps(warnings),
                 "id": media_id},
            )
            # The new walkthrough replaces the previous one for the same orientation.
            from app.media import soft_delete

            for old in s.execute(
                text("""SELECT * FROM media WHERE listing_id = :l AND kind = 'video' AND aspect = :a
                        AND id <> :id AND deleted_at IS NULL AND status IN ('ready', 'failed')"""),
                {"l": video.listing_id, "a": video.aspect, "id": media_id},
            ).all():
                soft_delete(s, old)
            s.execute(text("UPDATE listings SET updated_at = clock_timestamp() WHERE id = :id"), {"id": video.listing_id})
            _finish(s, job_id, "done", None, time.monotonic() - started)
            _notify(s, video, ready=True, warnings=warnings)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _finish(s, job_id: UUID, status: str, error: str | None, seconds: float) -> None:
    s.execute(
        text("""UPDATE processing_jobs SET status = :st, error = :e, finished_at = now(), locked_at = NULL,
                       worker_seconds = coalesce(worker_seconds, 0) + :sec WHERE id = :id"""),
        {"st": status, "e": error, "sec": round(seconds, 1), "id": job_id},
    )


WARNING_COPY = {
    "too_short": "it's quite short, so the scroll will feel fast",
    "low_resolution": "it's below 1080p, so it may look soft on large screens",
    "too_dark": "it's quite dark; a brighter recording will look better",
}


def _notify(s, video, ready: bool, warnings: list[str] | None = None, error: str | None = None) -> None:
    to = s.execute(text("SELECT email FROM users WHERE id = :id"), {"id": video.created_by}).scalar_one_or_none()
    if not to:
        return
    title = s.execute(text("SELECT title FROM listings WHERE id = :id"), {"id": video.listing_id}).scalar_one_or_none() or "your listing"
    if ready:
        notes = "".join(f"\n- {WARNING_COPY[w]}" for w in warnings or [])
        body = f"The walkthrough for {title} is ready to preview in your Studio."
        if notes:
            body += f"\n\nIt works, but a few things could be better:{notes}"
        email.send(email.Email(to=to, subject=f"Your walkthrough for {title} is ready", text=body))
    else:
        email.send(email.Email(to=to, subject=f"We couldn't process the walkthrough for {title}",
                               text=f"{error}\n\nYou can upload a new video from the listing's Media tab."))


def _fail(job_id: UUID, workspace_id: UUID, media_id: UUID, attempts: int, error: str, final: bool) -> None:
    with tenant_session(None, workspace_id) as s:
        if not final:
            s.execute(text("""UPDATE processing_jobs SET status = 'queued', locked_at = NULL, error = :e,
                                     run_after = now() + make_interval(mins => :m) WHERE id = :id"""),
                      {"e": error[:2000], "m": 5 * attempts, "id": job_id})
            return
        _finish(s, job_id, "failed", error[:2000], 0)
        s.execute(text("UPDATE media SET status = 'failed', error = :e, updated_at = now() WHERE id = :id"),
                  {"e": error[:500], "id": media_id})
        video = s.execute(text("SELECT * FROM media WHERE id = :id"), {"id": media_id}).first()
    with tenant_session(video.created_by, workspace_id) as s:
        _notify(s, video, ready=False, error=error)


def run_once() -> bool:
    """Processes the next job, if any. Returns whether there was one."""
    with tenant_session() as s:
        job = s.execute(text("SELECT * FROM claim_processing_job()")).first()
    if job is None:
        return False
    try:
        if job.attempts > MAX_ATTEMPTS:
            raise VideoRejected("We couldn't process this video after several tries. Try uploading it again.")
        process(job.job_id, job.workspace_id, job.media_id)
    except VideoRejected as e:
        _fail(job.job_id, job.workspace_id, job.media_id, job.attempts, str(e), final=True)
    except Exception as e:
        log.exception("video job %s failed (attempt %s)", job.job_id, job.attempts)
        final = job.attempts >= MAX_ATTEMPTS
        message = "Something went wrong while preparing this walkthrough. Try uploading it again." if final else str(e)
        _fail(job.job_id, job.workspace_id, job.media_id, job.attempts, message, final=final)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("worker started")
    while True:
        busy = run_once()
        if not busy and not run_exports():
            time.sleep(2)


if __name__ == "__main__":
    main()
