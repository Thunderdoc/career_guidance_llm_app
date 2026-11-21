"""Kaam-Vaani — voice-first, RAG-powered career + job-matching layer.

Additive layer on Career Guidance AI for the GAVS Tech4Bharat prototype
(team Hackastra). One module per master-prompt §4.2 area; every router
mounts under ``/api/v1/kv/*`` behind its env feature flag (flag off = 404,
as if the route never existed). See ``ARCHITECTURE.md`` §3 and
``docs/KAAM_VAANI_PLAN.md`` for the staged plan.
"""
