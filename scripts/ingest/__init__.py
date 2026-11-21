"""Kaam-Vaani RAG ingestion pipeline (Stage 2).

Fetch → clean → chunk → embed (TF-IDF at query time; no stored vectors
in v1) → upsert → versioned snapshot. See ``README.md`` in this package
for the refresh procedure and ``docs/SOURCES.md`` §5 for per-source
fetchability.
"""
