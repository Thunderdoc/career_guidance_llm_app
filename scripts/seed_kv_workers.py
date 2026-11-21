#!/usr/bin/env python3
"""Seed Kaam-Vaani sample workers + consents + outcomes (Stage 6).

Reads ``data/kv_sample_workers.json`` (10 fictional workers, 13
consents with varied fields/durations, 3 shortlists, 2 contact
requests, 2 hire outcomes incl. one with a day-30 follow-up) and
loads them into the target DB. Every worker is marked ``is_sample``
and every user lives under the ``.sample`` TLD, which cannot receive
mail. Nothing here is a real worker, and no consent here is a real
person's consent.

Requires the Stage 5 listings seed first (``scripts/seed_kv_listings.py``)
— consents name sample employers by key and listings by title.

One consent is revoked via the real store transition and one is
backdated (raw SQL in this script only, granted 10 days ago on a
7-day duration) and then flipped to expired by the store's own
``expire_overdue_consents`` — so the demo shows all three consent
states honestly.

Idempotent: if sample workers already exist, it prints a note and
exits 0 without changing anything. ``--force`` removes the old sample
rows first (``ConsentStore.delete_sample_data`` — audit rows stay, by
design: the audit log is append-only).

Usage:
    python scripts/seed_kv_workers.py [--db PATH] [--force]
    # --db defaults to the app's DATABASE_PATH (load_settings).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from career_guidance import db as db_layer  # noqa: E402
from career_guidance.config import load_settings  # noqa: E402
from career_guidance.kaamvaani.consent import ConsentStore  # noqa: E402
from career_guidance.kaamvaani.employers import EmployerStore  # noqa: E402
from career_guidance.migrations import migrate  # noqa: E402
from career_guidance.users import UserStore  # noqa: E402

SEED_FILE = ROOT / "data" / "kv_sample_workers.json"
LISTINGS_FILE = ROOT / "data" / "kv_sample_listings.json"
SEED_ACTOR = "seed-script"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _backdate_consent(db_path: str, consent_id: int, days_ago_granted: int = 10) -> None:
    """Move a consent's grant/expiry into the past (script-only raw
    SQL — there is deliberately no backdate method on the store).
    The store's lazy expiry then flips it to expired on first read."""
    granted = datetime.now(timezone.utc) - timedelta(days=days_ago_granted)
    expires = granted + timedelta(days=7)
    conn = db_layer.connect(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE kv_consents SET granted_at = ?, expires_at = ? WHERE id = ?",
                (granted.isoformat(), expires.isoformat(), consent_id),
            )
    finally:
        conn.close()


def seed(db_path: str, force: bool = False) -> dict:
    """Seed the DB at ``db_path``. Returns a summary dict. Raises
    SystemExit(2) when the Stage 5 listings seed has not run yet."""
    migrate(db_path)
    store = ConsentStore(db_path)
    employers = EmployerStore(db_path)
    users = UserStore(db_path)
    existing = store.count_sample_workers()
    if existing and not force:
        print(f"Already seeded ({existing} sample workers) — use --force to re-seed.")
        return {"skipped": True, "existing_sample_workers": existing}
    if force and existing:
        removed = store.delete_sample_data()
        print(f"--force: removed {removed.get('sample_workers', 0)} existing sample workers.")

    if employers.count_sample_listings() == 0:
        print(
            "ERROR: no sample employers/listings in this DB — "
            "run scripts/seed_kv_listings.py first."
        )
        raise SystemExit(2)

    listings_seed = _load_json(LISTINGS_FILE)
    employer_email = {e["key"]: e["email"] for e in listings_seed["employers"]}

    def employer_by_key(key: str):
        email = employer_email[key]
        user = users.upsert_login(email, "seed", "")
        employer = employers.get_employer_by_user(user.id)
        if employer is None:
            print(f"ERROR: sample employer {key!r} ({email}) not found — re-run the listings seed.")
            raise SystemExit(2)
        return employer

    def listing_for(employer_id: int, title: str | None):
        verified = employers.list_listings(employer_id=employer_id, status="verified")
        if not verified:
            print(f"ERROR: employer {employer_id} has no verified listings.")
            raise SystemExit(2)
        if title:
            for listing in verified:
                if listing.title == title:
                    return listing
            print(f"ERROR: no verified listing titled {title!r} for employer {employer_id}.")
            raise SystemExit(2)
        return verified[0]

    seed_data = _load_json(SEED_FILE)
    worker_ids: dict[str, str] = {}
    for item in seed_data["workers"]:
        user = users.upsert_login(item["email"], "seed", item["name"])
        worker_ids[item["key"]] = user.id
        store.save_worker_profile(
            user.id,
            skills=item["skills"],
            education=item.get("education", ""),
            city=item.get("city", ""),
            district=item.get("district", ""),
            income_monthly=item.get("income_monthly"),
            income_text=item.get("income_text", ""),
            goal_type=item.get("goal_type", "job"),
            interests=item.get("interests", []),
            language=item.get("language", "en"),
            is_sample=True,
        )

    consent_states: dict[str, int] = {}
    for item in seed_data["consents"]:
        employer = employer_by_key(item["employer"])
        listing = listing_for(employer.id, item.get("listing")) if item.get("listing") else None
        consent = store.grant_consent(
            worker_ids[item["worker"]],
            employer.id,
            item.get("fields"),
            duration_days=item.get("duration_days", 30),
            listing_id=listing.id if listing else None,
            actor=SEED_ACTOR,
        )
        if item.get("then") == "revoke":
            consent = store.revoke_consent(consent.id, worker_ids[item["worker"]], actor=SEED_ACTOR)
        elif item.get("then") == "expire":
            _backdate_consent(db_path, consent.id)
            store.expire_overdue_consents()
            consent = store.get_consent(consent.id) or consent
        consent_states[consent.status] = consent_states.get(consent.status, 0) + 1

    shortlists = 0
    for item in seed_data["shortlists"]:
        employer = employer_by_key(item["employer"])
        listing = listing_for(employer.id, item.get("listing"))
        store.add_shortlist(employer.id, listing.id, worker_ids[item["worker"]])
        shortlists += 1

    contact_requests = 0
    for item in seed_data["contact_requests"]:
        employer = employer_by_key(item["employer"])
        listing = listing_for(employer.id, item.get("listing"))
        store.create_contact_request(
            employer.id, listing.id, worker_ids[item["worker"]], item.get("message", "")
        )
        contact_requests += 1

    outcomes = 0
    for item in seed_data["outcomes"]:
        employer = employer_by_key(item["employer"])
        listing = listing_for(employer.id, item.get("listing"))
        employer_user = users.upsert_login(employer_email[item["employer"]], "seed", "")
        outcome = store.report_outcome(
            employer.id,
            listing.id,
            worker_ids[item["worker"]],
            item["outcome"],
            reported_by_user_id=employer_user.id,
            reporter_role="employer",
            note=item.get("note", ""),
        )
        followup = item.get("followup")
        if followup:
            store.record_followup(outcome.id, followup["day"], followup["status"])
        outcomes += 1

    summary = {
        "skipped": False,
        "workers": len(worker_ids),
        "consents": consent_states,
        "shortlists": shortlists,
        "contact_requests": contact_requests,
        "outcomes": outcomes,
    }
    print(f"Seeded workers: {len(worker_ids)}")
    print(f"Seeded consents: {consent_states}")
    print(f"Seeded shortlists: {shortlists}, contact requests: {contact_requests}")
    print(f"Seeded outcomes: {outcomes}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Kaam-Vaani sample workers.")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: DATABASE_PATH).")
    parser.add_argument("--force", action="store_true", help="Remove old sample rows first.")
    args = parser.parse_args(argv)
    db_path = args.db or load_settings().database_path
    seed(db_path, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
