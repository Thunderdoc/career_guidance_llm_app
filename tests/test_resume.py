"""Tests for safe resume text extraction."""

import pytest

from career_guidance.models import InvalidInputError
from career_guidance.resume import MAX_RESUME_BYTES, extract_resume_text


def test_txt_extraction():
    text = extract_resume_text("resume.txt", b"Python developer  with\nSQL skills")
    assert text == "Python developer with SQL skills"


def test_truncates_to_max_chars():
    text = extract_resume_text("resume.txt", b"a" * 9000, max_chars=100)
    assert len(text) == 100


def test_rejects_unknown_extension():
    with pytest.raises(InvalidInputError):
        extract_resume_text("resume.docx", b"data")


def test_rejects_oversized_file():
    with pytest.raises(InvalidInputError):
        extract_resume_text("resume.txt", b"x" * (MAX_RESUME_BYTES + 1))


def test_rejects_empty_content():
    with pytest.raises(InvalidInputError):
        extract_resume_text("resume.txt", b"   ")


def test_invalid_pdf_raises_safe_error():
    with pytest.raises(InvalidInputError):
        extract_resume_text("resume.pdf", b"not a real pdf")
