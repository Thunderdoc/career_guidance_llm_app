#!/usr/bin/env python3
"""Live end-to-end verification of Kaam-Vaani Stage 6 (consent,
employer matching, hire outcomes) against a RUNNING backend on a
scratch DB. Each step prints PASS/FAIL; the exit code is 0 only when
every step passes.

The flow: a worker saves a profile and grants a narrow consent to a
verified employer; the employer sees exactly the consented fields,
shortlists and contacts the worker, reports a hire and a day-30
follow-up; the worker revokes and the employer sees nothing; the
audit log shows every event. Negative cases: an unconsented employer
sees zero candidates, and an unverified employer cannot match.

Usage:
    # Terminal 1 — backend on a scratch DB (admin = boss@example.com):
    DATABASE_PATH=/tmp/kv-stage6-verify.db ADMIN_EMAILS=boss@example.com \\
      PUBLIC_URL=http://127.0.0.1:8102 \\
      python -m uvicorn backend.main:app --port 8102
    # Terminal 2:
    python scripts/verify_kv_stage6.py [--base-url http://127.0.0.1:8102]
"""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

import httpx

WORKER = "verify-worker@example.com"
EMPLOYER = "verify-shop@example.com"
OTHER_EMPLOYER = "verify-other@example.com"
ADMIN = "boss@example.com"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def login(client: httpx.Client, base: str, email: str) -> dict:
    r = client.post(f"{base}/api/v1/auth/magic-link", json={"email": email})
    assert r.status_code == 200, f"magic-link for {email}: {r.status_code} {r.text}"
    link = r.json()["dev_link"]
    # The dev link may carry the server's own PUBLIC_URL host — use
    # only its path + query against our base URL.
    parsed = urlparse(link)
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    r = client.get(f"{base}{path}", follow_redirects=False)
    assert r.status_code == 303, f"magic-link verify for {email}: {r.status_code} {r.text}"
    me = client.get(f"{base}/api/v1/auth/me").json()["user"]
    assert me["email"] == email, f"me mismatch: {me}"
    return me


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Kaam-Vaani Stage 6 live.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8102")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    # trust_env=False: the sandbox's proxy env vars are for external
    # egress and break httpx URL parsing; localhost needs no proxy.
    worker = httpx.Client(timeout=30.0, trust_env=False)
    employer = httpx.Client(timeout=30.0, trust_env=False)
    other = httpx.Client(timeout=30.0, trust_env=False)
    admin = httpx.Client(timeout=30.0, trust_env=False)

    # 1. Health + consent status (public).
    r = worker.get(f"{base}/api/v1/health")
    check("health 200", r.status_code == 200, r.text[:200])
    r = worker.get(f"{base}/api/v1/kv/consent/status")
    check(
        "consent status public", r.status_code == 200 and r.json()["enabled"] is True, r.text[:200]
    )

    # 2. Worker saves a profile.
    me = login(worker, base, WORKER)
    r = worker.put(
        f"{base}/api/v1/kv/worker-profile",
        json={
            "skills": ["electrical technician"],
            "education": "12th pass",
            "city": "Madurai",
            "district": "Madurai",
            "income_monthly": 12000,
            "goal_type": "job",
        },
    )
    check(
        "worker profile saved (skill normalised)",
        r.status_code == 200 and r.json()["profile"]["skills"] == ["electrical"],
        r.text[:200],
    )

    # 3. Employer registers, posts a listing; admin verifies both.
    login(employer, base, EMPLOYER)
    r = employer.post(
        f"{base}/api/v1/kv/employers/register",
        json={"business_name": "Verify Electricals", "city": "Madurai"},
    )
    employer_id = r.json()["employer"]["id"]
    r = employer.post(
        f"{base}/api/v1/kv/employers/listings",
        json={
            "title": "Electrician helper",
            "role_category": "electrician",
            "description": "Help with house wiring work. 10th pass.",
            "city": "Madurai",
            "district": "Madurai",
            "pay_monthly_min": 12000,
            "pay_monthly_max": 15000,
            "requirements": "Basic wiring knowledge.",
        },
    )
    listing_id = r.json()["listing"]["id"]
    login(admin, base, ADMIN)
    r1 = admin.post(
        f"{base}/api/v1/kv/admin/employers/{employer_id}/review", json={"approve": True}
    )
    r2 = admin.post(f"{base}/api/v1/kv/admin/listings/{listing_id}/review", json={"approve": True})
    check(
        "employer + listing verified",
        r1.status_code == 200 and r2.status_code == 200,
        f"employer review {r1.status_code}, listing review {r2.status_code}",
    )

    # 4. Unverified employer cannot match at all (negative).
    login(other, base, OTHER_EMPLOYER)
    other.post(
        f"{base}/api/v1/kv/employers/register",
        json={"business_name": "Verify Other", "city": "Madurai"},
    )
    r = other.post(
        f"{base}/api/v1/kv/employers/listings",
        json={"title": "Helper", "city": "Madurai"},
    )
    other_listing = r.json()["listing"]["id"]
    r = other.post(
        f"{base}/api/v1/kv/employers/matching/candidates", json={"listing_id": other_listing}
    )
    check("unverified employer cannot match (409)", r.status_code == 409, r.text[:200])

    # 5. No consent yet: verified employer sees zero candidates.
    r = employer.post(
        f"{base}/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id}
    )
    check(
        "no consent → 0 candidates", r.status_code == 200 and r.json()["count"] == 0, r.text[:200]
    )

    # 6. Worker grants a NARROW consent (skills + city only).
    r = worker.post(
        f"{base}/api/v1/kv/consent/grant",
        json={
            "employer_id": employer_id,
            "listing_id": listing_id,
            "fields": ["skills", "city"],
            "duration_days": 30,
        },
    )
    consent_id = r.json()["consent"]["id"]
    check(
        "grant narrow consent",
        r.status_code == 200 and r.json()["consent"]["fields"] == ["skills", "city"],
        r.text[:200],
    )
    check(
        "explanation names employer + fields",
        "Verify Electricals" in r.json()["explanation"]
        and "the work you can do (your skills)" in r.json()["explanation"],
        r.json().get("explanation", "")[:200],
    )

    # 7. Employer matches: exactly the consented fields, nothing more.
    r = employer.post(
        f"{base}/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id}
    )
    body = r.json()
    candidate = body["candidates"][0] if body.get("candidates") else None
    check("match → 1 candidate", r.status_code == 200 and body["count"] == 1, r.text[:200])
    check(
        "only consented fields shared",
        candidate is not None
        and candidate["profile"]["fields_shared"] == ["skills", "city"]
        and candidate["profile"]["skills"] == ["electrical"]
        and "income_monthly" not in candidate["profile"]
        and "contact" not in candidate["profile"],
        str(candidate)[:300] if candidate else "no candidate",
    )
    worker_user_id = candidate["worker_user_id"] if candidate else me["id"]
    check(
        "candidate score has explainable components",
        candidate is not None
        and set(candidate["components"]) == {"skill", "title", "city", "income"},
        str(candidate)[:300] if candidate else "no candidate",
    )

    # 8. Shortlist + contact request; worker sees the request.
    r = employer.post(
        f"{base}/api/v1/kv/employers/matching/shortlist",
        json={"listing_id": listing_id, "worker_user_id": worker_user_id},
    )
    check("shortlist", r.status_code == 200, r.text[:200])
    r = employer.post(
        f"{base}/api/v1/kv/employers/matching/contact-request",
        json={
            "listing_id": listing_id,
            "worker_user_id": worker_user_id,
            "message": "Can you come for a trial on Monday?",
        },
    )
    check("contact request", r.status_code == 200, r.text[:200])
    r = worker.get(f"{base}/api/v1/kv/consent/contact-requests")
    check(
        "worker sees the contact request",
        r.status_code == 200 and len(r.json()["requests"]) == 1,
        r.text[:200],
    )

    # 9. Hire outcome + day-30 follow-up; retention rate 1.0.
    r = employer.post(
        f"{base}/api/v1/kv/hire-outcomes",
        json={
            "listing_id": listing_id,
            "worker_user_id": worker_user_id,
            "outcome": "hired",
            "note": "Joined Monday",
        },
    )
    outcome_id = r.json()["outcome"]["id"]
    check("hire outcome reported", r.status_code == 200, r.text[:200])
    r = employer.post(
        f"{base}/api/v1/kv/hire-outcomes/{outcome_id}/followup",
        json={"day": 30, "status": "still_employed"},
    )
    check("day-30 follow-up", r.status_code == 200, r.text[:200])
    r = employer.get(f"{base}/api/v1/kv/employers/hire-outcomes?listing_id={listing_id}")
    summary = r.json()
    check(
        "retention day-30 rate 1.0",
        summary["counts"]["hired"] == 1 and summary["retention"]["day30"]["rate"] == 1.0,
        str(summary)[:300],
    )

    # 10. Worker revokes: employer sees nothing from the next call on.
    r = worker.post(f"{base}/api/v1/kv/consent/{consent_id}/revoke")
    check(
        "revoke", r.status_code == 200 and r.json()["consent"]["status"] == "revoked", r.text[:200]
    )
    r = employer.post(
        f"{base}/api/v1/kv/employers/matching/candidates", json={"listing_id": listing_id}
    )
    check("revoked → 0 candidates", r.status_code == 200 and r.json()["count"] == 0, r.text[:200])
    r = employer.get(f"{base}/api/v1/kv/employers/matching/shortlist?listing_id={listing_id}")
    view = r.json()["shortlist"]
    check(
        "shortlist entry survives revoke but hides data",
        len(view) == 1 and view[0]["consent_status"] == "revoked" and view[0]["profile"] is None,
        str(view)[:300],
    )

    # 11. Audit log shows grant, access, revoke (newest first).
    r = worker.get(f"{base}/api/v1/kv/consent/audit")
    actions = [e["action"] for e in r.json()["events"]]
    check(
        "audit has revoked/accessed/granted",
        actions[:3] == ["revoked", "accessed", "granted"],
        str(actions),
    )
    r = employer.get(f"{base}/api/v1/kv/employers/matching/audit")
    check(
        "employer audit mirrors the events",
        [e["action"] for e in r.json()["events"]][:3] == ["revoked", "accessed", "granted"],
        r.text[:200],
    )

    print()
    if failures:
        print(f"FAILED: {len(failures)} step(s): {', '.join(failures)}")
        return 1
    print("ALL STAGE 6 LIVE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
