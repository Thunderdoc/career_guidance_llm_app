"""ASGI entry point.

Platforms that auto-detect ``app.py`` (Vercel, Railway, Render, Fly, Deta, …)
import a top-level ``app`` / ``application`` / ``handler``. All three point at
the FastAPI application in :mod:`backend.main`, which also serves the built
front end from ``frontend/out`` when present.

    uvicorn app:app --host 0.0.0.0 --port 8000

The legacy Streamlit UI now lives in ``streamlit_app.py``.
"""

from backend.main import app

application = app
handler = app

__all__ = ["app", "application", "handler"]
