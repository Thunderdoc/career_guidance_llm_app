"""Kaam-Vaani video skill check — EXPERIMENTAL (Step 9.3).

One endpoint: upload a 30–60 s clip, get an indicative verdict
about the CLIP (is it a real recording with visible, moving
content?), never about skill. The clip is streamed to a temp
file, analysed, and deleted in a ``finally`` — nothing is stored,
and no result is persisted. Mounted behind ``KV_VIDEO_CHECK``.

Rate limit is strict (5 checks/hour per user): each check runs
ffmpeg/ffprobe on up to 50 MB, and the temp file lives on the
server's /tmp.
"""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.auth import Auth
from backend.kv_ratelimit import kv_limiter
from career_guidance.config import Settings
from career_guidance.kaamvaani.video import (
    MAX_UPLOAD_BYTES,
    VideoCheckError,
    VideoTimeout,
    VideoToolMissing,
    check_clip,
)
from career_guidance.users import User

_CHECK_LIMITER = kv_limiter(max_calls=5, per_seconds=3600)
_CHUNK = 1024 * 1024


def build_router(settings: Settings, current_user, auth: Auth) -> APIRouter:
    """Return the video-check router. ``auth`` is unused today —
    kept for the same signature as the other kv routers."""
    router = APIRouter(prefix="/api/v1/kv/video", tags=["kaam-vaani-video"])

    @router.get("/status")
    def status() -> dict:
        return {
            "enabled": True,
            "experimental": True,
            "label": "Indicative only — not a certificate.",
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "duration_seconds": [30, 60],
        }

    @router.post("/check")
    async def check(
        file: UploadFile = File(...),  # noqa: B008
        user: User = Depends(current_user),  # noqa: B008
    ) -> dict:
        """Analyse a 30–60 s clip. Signed-in users only. The clip is
        deleted immediately after analysis — it is never stored."""
        if not _CHECK_LIMITER.allow(user.id):
            raise HTTPException(429, "Too many video checks — try again later.")
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".clip") as tmp:
                tmp_path = tmp.name
                received = 0
                while True:
                    chunk = await file.read(_CHUNK)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "Clip exceeds 50 MB.")
                    tmp.write(chunk)
            if received == 0:
                raise HTTPException(422, "Empty file.")
            try:
                return check_clip(tmp_path)
            except VideoTimeout as error:
                raise HTTPException(503, str(error)) from error
            except VideoToolMissing as error:
                raise HTTPException(503, str(error)) from error
            except VideoCheckError as error:
                raise HTTPException(422, str(error)) from error
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    return router
