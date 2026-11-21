"""Video skill check — EXPERIMENTAL (Step 9.3).

What this is: a clip-VALIDITY check. It measures only that the
uploaded clip is a real recording of the stated length with
visible, moving content (duration, resolution, brightness, blank
frames, frame-to-frame motion). It does NOT assess skill, and no
number it returns may be read as a skill score.

What it is not: a certificate, a skill assessment, or a vision
model. There is no labelled training data and no vision model
here — the thresholds below are CHOSEN, not tuned, and are
documented as such. A coordinator-led practical check is the
reliable assessment; this check only tells the coordinator
whether the clip is worth watching.

Clips are never stored: the router streams the upload to a temp
file, this module analyses it, and the router deletes the file
in a ``finally``. No result is persisted either — the check is
stateless.
"""

from __future__ import annotations

import io
import json
import shutil
import statistics
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

#: The spec: a 30–60 second task clip.
MIN_DURATION_SECONDS = 30.0
MAX_DURATION_SECONDS = 60.0
#: Largest upload the router accepts (a 60 s phone clip is ~15–30 MB).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
#: Frames sampled, evenly spaced through the clip.
FRAMES_SAMPLED = 6
#: A frame whose mean brightness (0–255) is below this is "too dark".
DARK_MEAN = 20.0
#: A frame whose brightness stddev is below this is "blank" (a flat
#: colour, a lens cap, a frozen frame).
BLANK_STDDEV = 5.0
#: Mean frame-to-frame difference below this means the clip is
#: effectively static (a photo held up to the camera, a frozen feed).
STATIC_MOTION = 2.0
#: Frames are downscaled to this width before analysis — brightness
#: and motion statistics are scale-robust, and a 1080p frame costs
#: ~20x the pixels for no extra signal.
ANALYSIS_WIDTH = 160

#: The label every response carries — pinned by test.
INDICATIVE_LABEL = "Indicative only — not a certificate."
LIMITS_TEXT = (
    "This check measures only that the clip is a real recording of the stated length "
    "with visible, moving content. It does NOT assess skill. A coordinator-led "
    "practical check is the reliable assessment."
)


class VideoCheckError(ValueError):
    """The clip cannot be checked (bad file, wrong length, no video)."""


class VideoTimeout(VideoCheckError):
    """The analysis did not finish in time — a server-side failure,
    not a bad clip (the router answers 503, not 422)."""


class VideoToolMissing(RuntimeError):
    """ffmpeg/ffprobe is not installed where the backend runs."""


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise VideoToolMissing(f"{name} is not installed on this server.")
    return path


def _run(argv: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as error:
        raise VideoTimeout("Analysis timed out.") from error


def _probe(path: Path, timeout_seconds: int) -> dict:
    """ffprobe: duration + the first video stream's resolution."""
    result = _run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        timeout_seconds,
    )
    if result.returncode != 0:
        raise VideoCheckError("This file is not a readable video clip.")
    try:
        data = json.loads(result.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise VideoCheckError("This file is not a readable video clip.") from error
    video = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video is None:
        raise VideoCheckError("This file has no video stream.")
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except (TypeError, ValueError) as error:
        raise VideoCheckError("Could not read the clip's duration.") from error
    return {
        "duration": duration,
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
    }


def _extract_frame(path: Path, at_seconds: float, timeout_seconds: int) -> Image.Image:
    """One frame as a greyscale PIL image, downscaled for analysis."""
    result = _run(
        [
            _tool("ffmpeg"),
            "-v",
            "error",
            "-ss",
            f"{at_seconds:.2f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-",
        ],
        timeout_seconds,
    )
    if result.returncode != 0 or not result.stdout:
        raise VideoCheckError("Could not read frames from this clip.")
    try:
        image = Image.open(io.BytesIO(result.stdout)).convert("L")
    except (OSError, ValueError) as error:
        raise VideoCheckError("Could not read frames from this clip.") from error
    if image.width > ANALYSIS_WIDTH:
        image = image.resize(
            (ANALYSIS_WIDTH, max(1, int(image.height * ANALYSIS_WIDTH / image.width)))
        )
    return image


def check_clip(path: str | Path, *, timeout_seconds: int = 120) -> dict:
    """Analyse a clip file and return the indicative result.

    Raises ``VideoCheckError`` for an unusable clip (wrong length,
    no video, unreadable) and ``VideoToolMissing`` when ffmpeg is
    absent. The verdict is about clip validity only.
    """
    clip = Path(path)
    info = _probe(clip, timeout_seconds)
    duration = info["duration"]
    if duration < MIN_DURATION_SECONDS:
        raise VideoCheckError(
            f"Clip is {duration:.1f} seconds — a skill-check clip must be "
            f"{MIN_DURATION_SECONDS:.0f}–{MAX_DURATION_SECONDS:.0f} seconds."
        )
    if duration > MAX_DURATION_SECONDS:
        raise VideoCheckError(
            f"Clip is {duration:.1f} seconds — a skill-check clip must be "
            f"{MIN_DURATION_SECONDS:.0f}–{MAX_DURATION_SECONDS:.0f} seconds."
        )
    frames = [
        _extract_frame(clip, duration * (i + 0.5) / FRAMES_SAMPLED, timeout_seconds)
        for i in range(FRAMES_SAMPLED)
    ]
    means = [ImageStat.Stat(frame).mean[0] for frame in frames]
    stddevs = [ImageStat.Stat(frame).stddev[0] for frame in frames]
    diffs = [
        ImageStat.Stat(ImageChops.difference(frames[i], frames[i + 1])).mean[0]
        for i in range(len(frames) - 1)
    ]
    mean_brightness = round(statistics.fmean(means), 1)
    dark_frames = sum(1 for m in means if m < DARK_MEAN)
    blank_frames = sum(1 for s in stddevs if s < BLANK_STDDEV)
    motion = round(statistics.fmean(diffs), 1) if diffs else 0.0
    # A majority of bad frames fails the check — one dark frame in a
    # 6-frame sample is a lighting flicker, not a bad clip.
    majority = FRAMES_SAMPLED // 2 + 1
    checks = [
        {
            "name": "duration",
            "passed": True,
            "value": round(duration, 1),
            "detail": f"{MIN_DURATION_SECONDS:.0f}–{MAX_DURATION_SECONDS:.0f} s required",
        },
        {
            "name": "brightness",
            "passed": dark_frames < majority,
            "value": mean_brightness,
            "detail": (
                f"mean brightness 0–255; {dark_frames} of {FRAMES_SAMPLED} "
                f"frames below {DARK_MEAN:.0f}"
            ),
        },
        {
            "name": "blank_frames",
            "passed": blank_frames < majority,
            "value": blank_frames,
            "detail": f"frames with stddev below {BLANK_STDDEV:.0f} (flat colour / frozen)",
        },
        {
            "name": "motion",
            "passed": motion >= STATIC_MOTION,
            "value": motion,
            "detail": f"mean frame-to-frame difference; below {STATIC_MOTION:.1f} is static",
        },
    ]
    reasons = []
    if dark_frames >= majority:
        reasons.append(f"Clip is too dark in {dark_frames} of {FRAMES_SAMPLED} frames.")
    if blank_frames >= majority:
        reasons.append(f"Clip is blank or frozen in {blank_frames} of {FRAMES_SAMPLED} frames.")
    if motion < STATIC_MOTION:
        reasons.append("Clip shows no movement between frames.")
    usable = all(check["passed"] for check in checks)
    return {
        "verdict": "usable" if usable else "unusable",
        "label": INDICATIVE_LABEL,
        # Confidence is LOW by design: the check measures clip
        # properties only, and no skill inference is drawn from them.
        "confidence": "low",
        "duration_seconds": round(duration, 1),
        "resolution": f"{info['width']}x{info['height']}",
        "frames_sampled": FRAMES_SAMPLED,
        "checks": checks,
        "reasons": reasons,
        "limits": LIMITS_TEXT,
    }
