"""O*NET occupation ingestion — from the catalogue already in the repo.

No network: ``data/catalog/occupations.json`` (974 occupations, CC BY 4.0,
U.S. Department of Labor) is the source. Each occupation becomes one
document (title, description, skills, knowledge, tools, alternate titles,
job zone) chunked to 300–500 tokens with the occupation title as the
chunk header, so a retrieved chunk always says which occupation it is.
"""

from __future__ import annotations

import json
from pathlib import Path

from career_guidance.kaamvaani.rag import Chunk

from .common import chunk_text

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_PATH = ROOT / "data" / "catalog" / "occupations.json"

# As recorded in docs/SOURCES.md §1 (catalogue as shipped, verified date).
SOURCE_DATE = "2026-11-06"
LICENCE = "CC BY 4.0 (O*NET Database, U.S. Department of Labor, ETA)"
ONET_URL = "https://www.onetonline.org/link/summary/{occ_id}"


def occupation_document(occ: dict) -> str:
    """One occupation as plain text (description + tasks/skills/tools)."""
    parts = [str(occ.get("description", "")).strip()]
    skills = occ.get("skills") or []
    if skills:
        parts.append("Skills: " + ", ".join(str(s) for s in skills) + ".")
    knowledge = occ.get("knowledge") or []
    if knowledge:
        parts.append("Knowledge: " + ", ".join(str(k) for k in knowledge) + ".")
    tools = list(occ.get("technology") or []) + list(occ.get("hot_technology") or [])
    if tools:
        parts.append("Tools and technology: " + ", ".join(str(t) for t in tools) + ".")
    alt = occ.get("alt_titles") or []
    if alt:
        parts.append("Also known as: " + ", ".join(str(a) for a in alt) + ".")
    job_zone = occ.get("job_zone")
    if job_zone is not None:
        # "Preparation level", not "Job Zone": the O*NET label injects
        # the word "job" into all 974 occupation chunks, where it then
        # matches every job-related query equally and drowns the real
        # signal (measured: df[job] 95% before this change).
        parts.append(f"Preparation level: {job_zone}.")
    interests = occ.get("interests") or []
    if interests:
        parts.append("Interests: " + ", ".join(str(i) for i in interests) + ".")
    return "\n".join(p for p in parts if p)


def ingest_onet(catalog_path: str | Path = CATALOG_PATH, snapshot_version: str = "") -> list[Chunk]:
    """All occupations → chunks. One chunk per occupation in the common
    case (median document ≈ 260 words); longer occupations split with
    overlap."""
    occupations = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    for occ in occupations:
        occ_id = str(occ["id"])
        title = str(occ["title"])
        document = occupation_document(occ)
        if not document.strip():
            continue
        for index, text in enumerate(chunk_text(document, header=title)):
            chunks.append(
                Chunk(
                    source_id=f"onet:{occ_id}",
                    source_url=ONET_URL.format(occ_id=occ_id),
                    source_title=title,
                    source_date=SOURCE_DATE,
                    licence=LICENCE,
                    language="en",
                    topic="occupation",
                    chunk_index=index,
                    text=text,
                    snapshot_version=snapshot_version,
                )
            )
    return chunks
