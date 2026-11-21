"""Web source registry + fetchers (Stage 2).

Two kinds of web source:

* **Official pages** — fetched as HTML and reduced to visible text
  (``common.html_to_text``). Only pages that return usable text are
  ingested; JS shells and blocked hosts are recorded in the fetch log
  and in ``docs/SOURCES.md`` §5, never worked around by inventing
  content.
* **Wikipedia articles** (CC BY-SA 4.0) — fetched as plain text via the
  Action API. Used ONLY where the official source is unfetchable
  (EPFO/ESIC official sites block or drop the connection, PMKVY's site
  is unreachable, cybercrime advisories are unreachable). The licence
  and the fallback reason are recorded on every chunk and in
  ``docs/SOURCES.md`` §5. Two figure rules apply to Wikipedia chunks:
  (1) no MINIMUM-WAGE figures (what a worker must be paid) — no
  fetchable source carries them, so specific wage questions are refusal
  cases until an official minimum-wage source is fetchable; (2)
  statutory scheme thresholds that Wikipedia does carry (EPF/ESI
  ceilings) are ingested as-is with source + fetch date cited on every
  answer — they can go stale, and the EPFO article itself carries two
  different ceiling figures (₹15,000 historical, ₹25,000 current per
  the article), which ``docs/SOURCES.md`` §5 records honestly rather
  than resolving by guessing.

Every source records: URL, title, topic, language, licence, state /
district where relevant. Fetchability is re-tested on every refresh
run — a source that starts working appears in the next snapshot, and
one that stops working drops out with a fetch log entry.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from dataclasses import dataclass

from career_guidance.kaamvaani.rag import Chunk

from .common import (
    FetchResult,
    chunk_text,
    fetch_url,
    html_to_text,
    now_iso,
    polite_delay,
)

logger = logging.getLogger("kaamvaani.ingest.web")

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_LICENCE = "CC BY-SA 4.0 (Wikipedia, Wikimedia Foundation)"


@dataclass(frozen=True)
class WebSource:
    """One fetchable web source."""

    source_id: str
    url: str
    title: str
    topic: str
    language: str = "en"
    licence: str = ""
    state: str = ""
    district: str = ""
    kind: str = "page"  # "page" | "wikipedia"
    wikipedia_title: str = ""  # kind == "wikipedia" only


# Official pages verified fetchable with usable text (Stage 2 probes,
# 20 Nov 2026). Licence strings name the publisher; Government of India
# pages are public information published by the named body.
OFFICIAL_SOURCES: tuple[WebSource, ...] = (
    WebSource(
        source_id="web:swayam",
        url="https://swayam.gov.in/",
        title="SWAYAM — free online courses (Ministry of Education)",
        topic="courses",
        licence="Public information (Ministry of Education, Government of India)",
    ),
    WebSource(
        source_id="web:nptel",
        url="https://nptel.ac.in/",
        title="NPTEL — courses from the IITs and IISc",
        topic="courses",
        licence="Public information (NPTEL, IITs / IISc)",
    ),
    WebSource(
        source_id="web:nsdc",
        url="https://nsdcindia.org/",
        title="National Skill Development Corporation (NSDC)",
        topic="skilling",
        licence="Public information (NSDC)",
    ),
    WebSource(
        source_id="web:dgt",
        url="https://dgt.gov.in/en",
        title="Directorate General of Training — ITI trades (DGT)",
        topic="skilling",
        licence="Public information (DGT, Ministry of Skill Development)",
    ),
    WebSource(
        source_id="web:nqr",
        url="https://www.nqr.gov.in/",
        title="National Qualification Register (NQR)",
        topic="skilling",
        licence="Public information (NCVET / National Qualification Register)",
    ),
    WebSource(
        source_id="web:ncs",
        url="https://www.ncs.gov.in/",
        title="National Career Service (NCS)",
        topic="employment",
        licence="Public information (Ministry of Labour & Employment)",
    ),
    WebSource(
        source_id="web:myscheme",
        url="https://www.myscheme.gov.in/",
        title="myScheme — government schemes portal (MeitY)",
        topic="schemes",
        licence="Public information (MeitY, Government of India)",
    ),
    WebSource(
        source_id="web:tnlabour",
        url="https://labour.tn.gov.in/",
        title="Tamil Nadu Labour Department",
        topic="rights",
        licence="Public information (Government of Tamil Nadu)",
        state="Tamil Nadu",
    ),
    WebSource(
        source_id="web:ilo-india",
        url="https://www.ilo.org/india",
        title="International Labour Organization — India",
        topic="rights",
        licence="Public information (ILO)",
    ),
)

# Wikipedia fallbacks (see module docstring for why each is needed).
WIKIPEDIA_SOURCES: tuple[WebSource, ...] = (
    WebSource(
        source_id="wiki:epfo",
        url="https://en.wikipedia.org/wiki/Employees%27_Provident_Fund_Organisation",
        title="Employees' Provident Fund Organisation (Wikipedia)",
        topic="rights",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Employees' Provident Fund Organisation",
    ),
    WebSource(
        source_id="wiki:esic",
        url="https://en.wikipedia.org/wiki/Employees%27_State_Insurance",
        title="Employees' State Insurance (Wikipedia)",
        topic="rights",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Employees' State Insurance",
    ),
    WebSource(
        source_id="wiki:pmkvy",
        url="https://en.wikipedia.org/wiki/Pradhan_Mantri_Kaushal_Vikas_Yojana",
        title="Pradhan Mantri Kaushal Vikas Yojana (Wikipedia)",
        topic="skilling",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Pradhan Mantri Kaushal Vikas Yojana",
    ),
    WebSource(
        source_id="wiki:advance-fee-scam",
        url="https://en.wikipedia.org/wiki/Advance-fee_scam",
        title="Advance-fee scam (Wikipedia)",
        topic="scam",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Advance-fee scam",
    ),
    WebSource(
        source_id="wiki:code-on-wages",
        url="https://en.wikipedia.org/wiki/Code_on_Wages,_2019",
        title="Code on Wages, 2019 (Wikipedia)",
        topic="rights",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Code on Wages, 2019",
    ),
    WebSource(
        source_id="wiki:skill-india",
        url="https://en.wikipedia.org/wiki/Skill_India",
        title="Skill India (Wikipedia)",
        topic="skilling",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Skill India",
    ),
    WebSource(
        source_id="wiki:unorganised-workers-act",
        url="https://en.wikipedia.org/wiki/Unorganised_Workers%27_Social_Security_Act,_2008",
        title="Unorganised Workers' Social Security Act, 2008 (Wikipedia)",
        topic="rights",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Unorganised Workers' Social Security Act, 2008",
    ),
    WebSource(
        source_id="wiki:social-security-india",
        url="https://en.wikipedia.org/wiki/Social_security_in_India",
        title="Social security in India (Wikipedia)",
        topic="rights",
        licence=WIKIPEDIA_LICENCE,
        kind="wikipedia",
        wikipedia_title="Social security in India",
    ),
)

ALL_SOURCES: tuple[WebSource, ...] = OFFICIAL_SOURCES + WIKIPEDIA_SOURCES


def fetch_wikipedia(title: str) -> FetchResult:
    """Full plain-text extract of one Wikipedia article via the Action API."""
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "titles": title,
            "format": "json",
            "formatversion": "2",
        }
    )
    url = f"{WIKIPEDIA_API}?{query}"
    result = fetch_url(url)
    if not result.ok:
        return result
    try:
        data = json.loads(result.text)
        page = data["query"]["pages"][0]
    except (KeyError, IndexError, ValueError):
        return FetchResult(url=url, ok=False, error="unexpected Wikipedia API response")
    if page.get("missing"):
        return FetchResult(url=url, ok=False, status=404, error="Wikipedia article not found")
    return FetchResult(
        url=url,
        ok=True,
        status=result.status,
        bytes=result.bytes,
        text=page.get("extract", ""),
        final_url=url,
    )


def ingest_web_source(
    source: WebSource, snapshot_version: str, fetched_date: str = ""
) -> tuple[list[Chunk], FetchResult]:
    """Fetch one source and chunk its text. Returns (chunks, fetch result)
    — on a fetch failure the chunk list is empty and the caller records
    the failure instead of inventing content."""
    fetched_date = fetched_date or now_iso()[:10]
    if source.kind == "wikipedia":
        result = fetch_wikipedia(source.wikipedia_title)
        text = result.text if result.ok else ""
    else:
        result = fetch_url(source.url)
        text = html_to_text(result.text) if result.ok else ""
    if not result.ok or not text.strip():
        return [], result
    chunks = []
    for index, piece in enumerate(chunk_text(text, header=source.title)):
        chunks.append(
            Chunk(
                source_id=source.source_id,
                source_url=source.url,
                source_title=source.title,
                source_date=fetched_date,
                licence=source.licence,
                language=source.language,
                topic=source.topic,
                state=source.state,
                district=source.district,
                chunk_index=index,
                text=piece,
                snapshot_version=snapshot_version,
            )
        )
    return chunks, result


def ingest_all_web(
    snapshot_version: str, sources: tuple[WebSource, ...] = ALL_SOURCES
) -> tuple[list[Chunk], list[dict]]:
    """Fetch every registered web source (1 s apart). Returns (chunks,
    fetch log entries) — failures are logged, never fatal."""
    chunks: list[Chunk] = []
    log: list[dict] = []
    for source in sources:
        found, result = ingest_web_source(source, snapshot_version)
        chunks.extend(found)
        log.append(
            {
                "source_id": source.source_id,
                "url": source.url,
                "ok": result.ok,
                "status": result.status,
                "bytes": result.bytes,
                "chunks": len(found),
                "error": result.error,
            }
        )
        logger.info(
            "ingest %s: ok=%s status=%s chunks=%d %s",
            source.source_id,
            result.ok,
            result.status,
            len(found),
            result.error,
        )
        polite_delay()
    return chunks, log
