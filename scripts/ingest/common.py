"""Shared ingestion helpers: polite fetching, HTML→text, chunking, snapshots.

Only the standard library + PyYAML (already a dependency) are used, so
the pipeline runs anywhere the app runs. No JavaScript is executed: pages
that render their content client-side yield little or no text and are
recorded as such in ``docs/SOURCES.md`` (the pipeline never invents
content to fill the gap).
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

logger = logging.getLogger("kaamvaani.ingest")

USER_AGENT = (
    "Kaam-Vaani-ingest/1.0 (GAVS Tech4Bharat prototype; educational, "
    "non-commercial; fetches public pages once per run)"
)
FETCH_TIMEOUT_SECONDS = 30
FETCH_DELAY_SECONDS = 1.0  # polite gap between fetches to the same host

# Chunking targets (master prompt §5.1: semantic, 300–500 tokens, overlap).
CHUNK_MIN_TOKENS = 300
CHUNK_MAX_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
CHUNK_MIN_KEEP_TOKENS = 30  # fragments below this are dropped as boilerplate


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FetchResult:
    """One fetch attempt — success or failure, both recorded honestly."""

    url: str
    ok: bool
    status: int | None = None
    bytes: int = 0
    text: str = ""
    error: str = ""
    final_url: str = ""


def fetch_url(url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> FetchResult:
    """GET ``url`` with a polite UA. Network/HTTP failures return a
    FetchResult with ok=False — the caller records the failure, the
    pipeline never retries in a tight loop and never fakes content."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return FetchResult(
                url=url,
                ok=True,
                status=response.status,
                bytes=len(body),
                text=body.decode("utf-8", errors="replace"),
                final_url=response.geturl(),
            )
    except urllib.error.HTTPError as error:
        return FetchResult(url=url, ok=False, status=error.code, error=f"HTTP {error.code}")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        return FetchResult(url=url, ok=False, error=f"{type(error).__name__}: {error}")


# --------------------------------------------------------------------------- #
# HTML → text (stdlib html.parser; no JS execution)
# --------------------------------------------------------------------------- #

_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "form",
    "iframe",
    "svg",
    "select",
    "button",
}
_BLOCK_TAGS = {
    "p",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "td",
    "th",
    "tr",
    "div",
    "section",
    "article",
    "blockquote",
    "dd",
    "dt",
}


class _TextExtractor(HTMLParser):
    """Collects visible block text; skips chrome (nav/header/footer/...)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._blocks: list[str] = []
        self._current: list[str] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._current.append(text)

    def _flush(self) -> None:
        if self._current:
            self._blocks.append(" ".join(self._current))
            self._current = []

    def text(self) -> str:
        self._flush()
        lines = []
        for block in self._blocks:
            cleaned = re.sub(r"\s+", " ", block).strip()
            if len(cleaned) >= 20:  # drop nav crumbs / single-word fragments
                lines.append(cleaned)
        return "\n".join(lines)


def html_to_text(html: str) -> str:
    """Visible text of an HTML page ("" when the page is a JS shell)."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # pragma: no cover - malformed HTML is tolerated
        logger.warning("HTML parse failed; returning partial text", exc_info=True)
    return parser.text()


def html_title(html: str) -> str:
    """<title> of a page ("" when absent)."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


# --------------------------------------------------------------------------- #
# Chunking — sentence-aware, 300–500 tokens, ~50-token overlap
# --------------------------------------------------------------------------- #

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]
    return [re.sub(r"\s+", " ", s) for s in parts]


def _word_count(text: str) -> int:
    return len(text.split())


def chunk_text(text: str, header: str = "") -> list[str]:
    """Split ``text`` into 300–500-token chunks with ~50 tokens of overlap.

    Sentences are the unit: a chunk grows until it reaches the minimum,
    then closes at the next sentence boundary (or the maximum, where a
    long sentence is hard-split by words). ``header`` (e.g. an occupation
    title) is prepended to every chunk so a chunk retrieved on its own
    still says what it is about. Fragments below 30 tokens are dropped.
    """
    sentences = _sentences(text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    overlap: list[str] = []

    def flush() -> None:
        nonlocal current, current_tokens, overlap
        if not current:
            return
        body = " ".join(current)
        if _word_count(body) >= CHUNK_MIN_KEEP_TOKENS:
            chunks.append(f"{header}\n{body}" if header else body)
        # Overlap: carry the tail (~50 tokens) into the next chunk.
        tail: list[str] = []
        tail_tokens = 0
        for sentence in reversed(current):
            tail.insert(0, sentence)
            tail_tokens += _word_count(sentence)
            if tail_tokens >= CHUNK_OVERLAP_TOKENS:
                break
        overlap = tail
        current, current_tokens = [], 0

    for sentence in sentences:
        words = _word_count(sentence)
        if words > CHUNK_MAX_TOKENS:
            # One very long sentence: hard-split it by words.
            flush()
            tokens = sentence.split()
            for i in range(0, len(tokens), CHUNK_MAX_TOKENS):
                piece = " ".join(tokens[i : i + CHUNK_MAX_TOKENS])
                if _word_count(piece) >= CHUNK_MIN_KEEP_TOKENS:
                    chunks.append(f"{header}\n{piece}" if header else piece)
            continue
        if current_tokens + words > CHUNK_MAX_TOKENS and current_tokens >= CHUNK_MIN_TOKENS:
            flush()
            current, current_tokens = list(overlap), _word_count(" ".join(overlap))
            overlap = []
        current.append(sentence)
        current_tokens += words
    flush()
    return chunks


# --------------------------------------------------------------------------- #
# Snapshot files (JSONL + .meta.json sidecar)
# --------------------------------------------------------------------------- #


@dataclass
class SnapshotMeta:
    """Provenance for one snapshot version."""

    version: str
    generated_at: str = ""
    chunks: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    fetch_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "generated_at": self.generated_at or now_iso(),
            "chunks": self.chunks,
            "sources": self.sources,
            "fetch_results": self.fetch_results,
        }


def write_snapshot(path: str | Path, chunks: list[dict], meta: SnapshotMeta) -> Path:
    """Write ``<path>.jsonl`` (one chunk object per line) + the
    ``<path>.meta.json`` sidecar. Returns the JSONL path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta.chunks = len(chunks)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    meta_path = path.with_suffix("").with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def polite_delay() -> None:
    """Polite gap between fetches (one second)."""
    time.sleep(FETCH_DELAY_SECONDS)
