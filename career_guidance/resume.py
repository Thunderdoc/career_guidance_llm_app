"""Safe resume text extraction from uploaded files."""

import logging
from io import BytesIO

from career_guidance.models import InvalidInputError

logger = logging.getLogger("career_guidance.resume")

MAX_RESUME_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf")


def extract_resume_text(filename: str, data: bytes, max_chars: int = 8000) -> str:
    """Extract plain text from an uploaded resume file.

    Args:
        filename: Original file name, used to determine the file type.
        data: Raw file bytes.
        max_chars: Maximum number of characters to keep.

    Returns:
        Whitespace-normalized resume text, truncated to ``max_chars``.

    Raises:
        InvalidInputError: If the file is too large, unsupported, or unreadable.
    """
    if len(data) > MAX_RESUME_BYTES:
        raise InvalidInputError("Resume file is too large (max 5 MB).")

    name = (filename or "").lower()
    if name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    elif name.endswith(".pdf"):
        text = _extract_pdf(data)
    else:
        raise InvalidInputError(
            "Unsupported file type. Upload a .txt, .md, or .pdf resume."
        )

    text = " ".join(text.split())
    if not text:
        raise InvalidInputError("Could not extract any text from the resume.")
    return text[:max_chars]


def _extract_pdf(data: bytes) -> str:
    """Extract text from PDF bytes, raising a safe error on failure."""
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - env specific
        raise InvalidInputError("PDF support is not installed.") from error
    try:
        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as error:
        logger.warning("PDF extraction failed: %s", error)
        raise InvalidInputError(
            "Could not read the PDF file. Try exporting it again or use a .txt file."
        ) from error
