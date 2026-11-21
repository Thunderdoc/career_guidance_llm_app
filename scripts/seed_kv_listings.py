#!/usr/bin/env python3
"""Seed Kaam-Vaani sample employers + listings (Stage 5).

Reads ``data/kv_sample_listings.json`` (7 fictional employers, 40
legit listings, 5 deliberately fake listings) and loads them into the
target DB. Every listing is marked ``is_sample`` and the API/UI label
it as sample data; sample users live under the ``.sample`` TLD, which
cannot receive mail. Nothing here is a real job, employer or person.

Statuses use the real store transitions: employers go pending →
verified/flagged via ``set_employer_status`` (reviewed_by
``seed-script``); listings go pending → verified the same way, so a
listing can only land verified when its employer is verified. Fake
listings run the scam checker and land with whatever status the rules
give them — the script WARNS (loudly, non-zero exit) if a fake
listing scores below the flag threshold, because the demo depends on
detection working.

Idempotent: if sample listings already exist, it prints a note and
exits 0 without changing anything. ``--force`` removes the old sample
rows first (listings, then their employers) and re-seeds.

Usage:
    python scripts/seed_kv_listings.py [--db PATH] [--force]
    # --db defaults to the app's DATABASE_PATH (load_settings).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from career_guidance.config import load_settings  # noqa: E402
from career_guidance.kaamvaani.employers import EmployerStore  # noqa: E402
from career_guidance.kaamvaani.scam import FLAG_THRESHOLD, check_listing  # noqa: E402
from career_guidance.migrations import migrate  # noqa: E402
from career_guidance.users import UserStore  # noqa: E402

SEED_FILE = ROOT / "data" / "kv_sample_listings.json"
SEED_REVIEWER = "seed-script"
SEED_NOTE = "Sample data seeded by scripts/seed_kv_listings.py."


def _load_seed() -> dict:
    with open(SEED_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def seed(db_path: str, force: bool = False) -> dict:
    """Seed the DB at ``db_path``. Returns a summary dict. Raises
    SystemExit(2) when a fake listing fails to flag (the demo's scam
    detection must work) — the DB is left as-is up to that point."""
    migrate(db_path)
    store = EmployerStore(db_path)
    users = UserStore(db_path)
    existing = store.count_sample_listings()
    if existing and not force:
        print(f"Already seeded ({existing} sample listings) — use --force to re-seed.")
        return {"skipped": True, "existing_sample_listings": existing}
    if force and existing:
        removed = store.delete_sample_listings()
        print(f"--force: removed {removed} existing sample listings.")

    seed_data = _load_seed()
    employers_by_key: dict[str, object] = {}
    employer_counts: dict[str, int] = {}
    for item in seed_data["employers"]:
        user = users.upsert_login(item["email"], "seed", item["business_name"])
        users.set_role(user.id, "employer")
        existing_profile = store.get_employer_by_user(user.id)
        if existing_profile is not None:
            if force:
                store.delete_employer(existing_profile.id)
            else:
                employers_by_key[item["key"]] = existing_profile
                employer_counts[existing_profile.status] = (
                    employer_counts.get(existing_profile.status, 0) + 1
                )
                continue
        employer = store.create_employer(
            user.id,
            business_name=item["business_name"],
            contact_name=item.get("contact_name", ""),
            phone_e164=item.get("phone_e164", ""),
            email=item["email"],
            city=item.get("city", ""),
            district=item.get("district", ""),
            state=item.get("state", "Tamil Nadu"),
            business_type=item.get("business_type", ""),
            description=item.get("description", ""),
        )
        status = item.get("status", "pending")
        if status in ("verified", "flagged"):
            employer = store.set_employer_status(
                employer.id, status, reviewer=SEED_REVIEWER, note=SEED_NOTE
            )
        if item.get("endorsed_by"):
            employer = store.set_endorsement(
                employer.id,
                item["endorsed_by"],
                item.get("endorsed_by_type", ""),
                item.get("endorsement_note", ""),
            )
        employers_by_key[item["key"]] = employer
        employer_counts[employer.status] = employer_counts.get(employer.status, 0) + 1

    listing_counts: dict[str, int] = {}
    warnings: list[str] = []
    for item in seed_data["listings"]:
        employer = employers_by_key[item["employer"]]
        payload = {k: v for k, v in item.items() if k not in ("employer", "status")}
        check = check_listing(payload, employer.to_dict(), duplicate=False)
        wanted = item.get("status", "pending")
        if wanted == "fake":
            if check.score < FLAG_THRESHOLD:
                warnings.append(
                    f"FAKE LISTING NOT FLAGGED: {item['title']!r} scored "
                    f"{check.score} (< {FLAG_THRESHOLD}) — fix the seed data."
                )
            listing = store.create_listing(
                employer.id,
                status=check.recommended_status,
                risk_score=check.score,
                risk_flags=[f.to_dict() for f in check.flags],
                is_sample=True,
                **payload,
            )
        else:
            listing = store.create_listing(
                employer.id,
                status="pending",
                risk_score=check.score,
                risk_flags=[f.to_dict() for f in check.flags],
                is_sample=True,
                **payload,
            )
            if wanted == "verified":
                listing = store.set_listing_status(
                    listing.id, "verified", reviewer=SEED_REVIEWER, note=SEED_NOTE
                )
        listing_counts[listing.status] = listing_counts.get(listing.status, 0) + 1

    summary = {
        "skipped": False,
        "employers": employer_counts,
        "listings": listing_counts,
        "warnings": warnings,
    }
    print(f"Seeded employers: {employer_counts}")
    print(f"Seeded listings: {listing_counts}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Kaam-Vaani sample listings.")
    parser.add_argument("--db", default=None, help="SQLite DB path (default: DATABASE_PATH).")
    parser.add_argument("--force", action="store_true", help="Remove old sample rows first.")
    args = parser.parse_args(argv)
    db_path = args.db or load_settings().database_path
    summary = seed(db_path, force=args.force)
    if summary.get("warnings"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
