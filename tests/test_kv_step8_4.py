"""Kaam-Vaani Step 8.4: duplicate detection (exact hash + Bloom +
shingle Jaccard).

Covers: normalisation / fingerprint / shingles / Jaccard units,
the Bloom filter (sizing math, no false negatives, measured FP
rate at pilot scale and at the 10k design point), the index
(exact vs near, scope, best-match selection, exclude_id), the
labelled-set precision/recall gate (real seed listings +
synthetic near-duplicates, labelled honestly), the store
integration (including cache invalidation), and the router end
to end (the duplicate flag in the scam check).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from career_guidance.kaamvaani.dedup import (
    JACCARD_THRESHOLD,
    BloomFilter,
    DuplicateIndex,
    jaccard,
    listing_fingerprint,
    normalize_text,
    text_shingles,
)
from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.migrations import migrate
from tests.conftest import login

SEED = json.loads((Path(__file__).parent.parent / "data" / "kv_sample_listings.json").read_text())[
    "listings"
]

TITLE = "Electrician helper"
DESC = "Help our electricians with house wiring, switchboard fitting and repair calls."
CITY = "Madurai"


# --------------------------------------------------------------------------- #
# Units: normalise / fingerprint / shingles / Jaccard
# --------------------------------------------------------------------------- #


def test_normalize_text():
    assert normalize_text("  Electrician   HELPER\n") == "electrician helper"
    assert normalize_text("") == ""


def test_fingerprint_stable_under_case_and_space():
    base = listing_fingerprint(TITLE, DESC, CITY)
    assert listing_fingerprint("  electrician HELPER ", DESC, CITY) == base
    assert listing_fingerprint(TITLE, "  " + DESC + "  ", CITY) == base
    assert listing_fingerprint(TITLE, DESC, "madurai") == base
    # But sensitive to every field.
    assert listing_fingerprint("Wireman assistant", DESC, CITY) != base
    assert listing_fingerprint(TITLE, "Different work.", CITY) != base
    assert listing_fingerprint(TITLE, DESC, "Chennai") != base


def test_text_shingles_adaptive():
    assert text_shingles("one two three four") == {
        "one two three",
        "two three four",
    }
    assert text_shingles("electrician helper") == {"electrician helper"}  # 2 words -> 1 2-shingle
    assert text_shingles("helper") == {"helper"}  # 1 word -> 1 1-shingle
    assert text_shingles("") == set()
    assert text_shingles("  HELPER   wanted ") == {"helper wanted"}


def test_jaccard_edges():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0
    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard(set(), set()) == 0.0  # two empty texts are not a duplicate
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


# --------------------------------------------------------------------------- #
# Bloom filter
# --------------------------------------------------------------------------- #


def test_bloom_sizing_math():
    bloom = BloomFilter.sized_for(10_000, 0.01)
    assert bloom.num_bits == 95851
    assert bloom.num_hashes == 7
    assert bloom.theoretical_fp_rate() == 0.0  # nothing inserted yet
    with pytest.raises(ValueError, match="expected_items"):
        BloomFilter.sized_for(0, 0.01)
    with pytest.raises(ValueError, match="fp_rate"):
        BloomFilter.sized_for(100, 1.5)


def test_bloom_no_false_negatives():
    bloom = BloomFilter.sized_for(100, 0.01)
    items = [f"item-{i}" for i in range(100)]
    for item in items:
        bloom.add(item)
    assert all(item in bloom for item in items)


def test_bloom_measured_fp_pilot_scale():
    # The 45 seed fingerprints in the production-sized filter:
    # measured 0 false positives over 10,000 probes (deterministic
    # — sha256-based positions, same seed data every run).
    bloom = BloomFilter.sized_for(10_000, 0.01)
    for listing in SEED:
        bloom.add(listing_fingerprint(listing["title"], listing["description"], listing["city"]))
    assert bloom.inserted == 45
    assert bloom.theoretical_fp_rate() < 0.000001
    rng = random.Random(99)
    false_pos = sum(1 for i in range(10_000) if f"probe-{rng.getrandbits(64)}-{i}" in bloom)
    assert false_pos == 0


def test_bloom_measured_fp_design_point():
    # Filled to the 10k design point, the measured rate must sit
    # near the 1% design rate (measured 0.0095 on 21 Nov 2026).
    bloom = BloomFilter.sized_for(10_000, 0.01)
    for i in range(10_000):
        bloom.add(f"design-item-{i}")
    assert bloom.theoretical_fp_rate() == pytest.approx(0.01, abs=0.001)
    rng = random.Random(7)
    false_pos = sum(1 for i in range(10_000) if f"design-probe-{rng.getrandbits(64)}-{i}" in bloom)
    assert false_pos / 10_000 < 0.02


# --------------------------------------------------------------------------- #
# DuplicateIndex
# --------------------------------------------------------------------------- #


def _index():
    rows = [
        (1, 10, TITLE, DESC, CITY, "2026-11-01T00:00:00"),
        (
            2,
            10,
            "Wireman assistant",
            "Assist wiremen on new building wiring projects.",
            CITY,
            "2026-11-02T00:00:00",
        ),
        (3, 11, TITLE, DESC, CITY, "2026-11-03T00:00:00"),  # other employer, same text
        (4, 10, TITLE, DESC, "Chennai", "2026-11-04T00:00:00"),  # other city
    ]
    return DuplicateIndex(rows)


def test_index_exact_match():
    match = _index().find(10, TITLE, DESC, CITY)
    assert match is not None
    assert match.listing_id == 1
    assert match.method == "exact"
    assert match.similarity == 1.0


def test_index_near_match_reworded():
    match = _index().find(10, "Urgent electrician helper", DESC, CITY)
    assert match is not None
    assert match.listing_id == 1
    assert match.method == "near"
    assert match.similarity >= JACCARD_THRESHOLD


def test_index_scope_and_exclude():
    index = _index()
    # Other employer with identical text: not an automatic match.
    assert index.find(11, TITLE, DESC, CITY, exclude_id=3) is None
    # Other city: not a match.
    assert index.find(10, TITLE, DESC, "Salem") is None
    # Excluded id: the only exact match is skipped.
    assert index.find(10, TITLE, DESC, CITY, exclude_id=1) is None
    # Same title, different description: a new opening, not a duplicate.
    assert index.find(10, TITLE, "Night-shift warehouse packing work. Load trucks.", CITY) is None


def test_index_empty():
    assert DuplicateIndex([]).find(10, TITLE, DESC, CITY) is None


# --------------------------------------------------------------------------- #
# Labelled-set precision / recall gate
# --------------------------------------------------------------------------- #


def _variants(listing, rng):
    t, d = listing["title"], listing["description"]

    def drop_word(text):
        words = text.split()
        return " ".join(words[:-1]) if len(words) > 1 else text

    def drop_sentence(text):
        parts = [p.strip() for p in text.split(".") if p.strip()]
        return ". ".join(parts[:-1]) + "." if len(parts) > 1 else text

    def shuffle_sentences(text):
        parts = [p.strip() for p in text.split(".") if p.strip()]
        if len(parts) <= 1:
            return text
        rng.shuffle(parts)
        return ". ".join(parts) + "."

    out = [
        ("exact copy", t, d),
        ("title word dropped", drop_word(t), d),
        ("title reordered", " ".join(reversed(t.split())), d),
        ("title urgent prefix", "Urgent " + t, d),
        ("desc sentence dropped", t, drop_sentence(d)),
        ("desc sentences shuffled", t, shuffle_sentences(d)),
        (
            "desc fillers inserted",
            t,
            d.replace(" work", " good work").replace(" help", " please help"),
        ),
        ("title + desc edited", drop_word(t), drop_sentence(d)),
    ]
    # Skip no-op variants (they are exact copies, not near ones).
    return [(k, a, b) for k, a, b in out if (a, b) != (t, d) or k == "exact copy"]


def _labelled_pairs():
    # Two loops (all positives, then all negatives), matching the
    # tuning script's RNG order — interleaving them shifts the
    # shuffle outcomes and changes the pair count by one.
    rng = random.Random(20261121)
    pairs = []  # (is_duplicate, jaccard, fingerprint_equal)
    for listing in SEED:
        base = text_shingles(f"{listing['title']} {listing['description']}")
        base_fp = listing_fingerprint(listing["title"], listing["description"], listing["city"])
        for _, t, d in _variants(listing, rng):
            pairs.append(
                (
                    True,
                    jaccard(base, text_shingles(f"{t} {d}")),
                    listing_fingerprint(t, d, listing["city"]) == base_fp,
                )
            )
    for listing in SEED:
        base = text_shingles(f"{listing['title']} {listing['description']}")
        base_fp = listing_fingerprint(listing["title"], listing["description"], listing["city"])
        other = rng.choice([o for o in SEED if o is not listing])
        for t, d in [
            (other["title"], other["description"]),
            (listing["title"], other["description"]),  # hard negative
        ]:
            pairs.append(
                (
                    False,
                    jaccard(base, text_shingles(f"{t} {d}")),
                    listing_fingerprint(t, d, listing["city"]) == base_fp,
                )
            )
    return pairs


def test_labelled_precision_recall():
    pairs = _labelled_pairs()
    assert len(pairs) == 369  # 279 positive, 90 negative
    tp = sum(1 for d, s, f in pairs if d and (f or s >= JACCARD_THRESHOLD))
    fp = sum(1 for d, s, f in pairs if not d and (f or s >= JACCARD_THRESHOLD))
    fn = sum(1 for d, s, f in pairs if d and not (f or s >= JACCARD_THRESHOLD))
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    # Measured 21 Nov 2026: precision 1.000, recall 0.907 at 0.5.
    assert precision == 1.0
    assert recall >= 0.90


# --------------------------------------------------------------------------- #
# Store integration
# --------------------------------------------------------------------------- #


def _store(tmp_path, name="kv84.db") -> EmployerStore:
    path = str(tmp_path / name)
    migrate(path)
    return EmployerStore(path)


def _employer(store, user_id="u-emp", **overrides):
    data = {
        "business_name": "Murugan Electricals",
        "contact_name": "Murugan",
        "city": "Madurai",
        "district": "Madurai",
        "business_type": "Electrical shop",
        "description": "House wiring and repair shop in Madurai.",
    }
    data.update(overrides)
    return store.create_employer(user_id, **data)


def _listing(**overrides):
    data = {
        "title": TITLE,
        "role_category": "electrician",
        "description": DESC,
        "city": CITY,
        "district": "Madurai",
        "pay_monthly_min": 12000,
        "pay_monthly_max": 15000,
        "work_type": "full-time",
        "openings": 2,
        "requirements": "Basic wiring knowledge.",
        "contact_info": "Murugan, 98430 12345, 12 Main Road, Madurai.",
    }
    data.update(overrides)
    return data


def test_store_find_duplicate_paths(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    other = _employer(store, user_id="u-emp2", business_name="Other Shop")
    listing = store.create_listing(employer.id, **_listing())
    # Exact repost.
    assert store.find_duplicate(employer.id, TITLE, CITY, DESC) is not None
    # Reworded repost (near-duplicate).
    assert store.find_duplicate(employer.id, "Urgent electrician helper", CITY, DESC) is not None
    # Same title, different description: not a duplicate.
    assert (
        store.find_duplicate(employer.id, TITLE, CITY, "Night-shift warehouse packing work.")
        is None
    )
    # Other employer / other city / excluded id: no match.
    assert store.find_duplicate(other.id, TITLE, CITY, DESC) is None
    assert store.find_duplicate(employer.id, TITLE, "Salem", DESC) is None
    assert store.find_duplicate(employer.id, TITLE, CITY, DESC, exclude_id=listing.id) is None


def test_store_dup_index_cache_invalidated_on_writes(tmp_path):
    store = _store(tmp_path)
    employer = _employer(store)
    store.create_listing(employer.id, **_listing())
    assert store._dup_index is None
    assert store.find_duplicate(employer.id, TITLE, CITY, DESC) is not None
    assert store._dup_index is not None
    # A listing created after the index built must still be found.
    second = store.create_listing(
        employer.id, **_listing(title="Plumber helper", description="Fix taps and pipes.")
    )
    assert store._dup_index is None  # create invalidated the cache
    found = store.find_duplicate(employer.id, "Plumber helper", CITY, "Fix taps and pipes.")
    assert found is not None and found.id == second.id
    # Deleting it removes it from the index.
    assert store.delete_listing(second.id) is True
    assert store.find_duplicate(employer.id, "Plumber helper", CITY, "Fix taps and pipes.") is None


# --------------------------------------------------------------------------- #
# Router end to end
# --------------------------------------------------------------------------- #


def _register_employer(client, email="shop@example.com"):
    login(client, email)
    r = client.post(
        "/api/v1/kv/employers/register",
        json={"business_name": "Murugan Electricals", "city": "Madurai"},
    )
    assert r.status_code == 200, r.text
    return r.json()["employer"]


def test_router_duplicate_flag_in_check(client):
    _register_employer(client)
    listing = {"title": TITLE, "description": DESC, "city": CITY}
    r = client.post("/api/v1/kv/employers/listings", json=listing)
    assert r.status_code == 200, r.text
    # An identical repost carries the duplicate flag (25 points).
    r = client.post("/api/v1/kv/employers/listings/check", json=listing)
    assert r.status_code == 200, r.text
    check = r.json()["check"]
    flag_ids = [f["id"] for f in check["flags"]]
    assert "duplicate" in flag_ids
    assert check["score"] >= 25
    # A genuinely different job does not.
    other = {
        "title": "Plumber helper",
        "description": "Fix taps and pipes in homes across Madurai. Day shift.",
        "city": CITY,
    }
    r = client.post("/api/v1/kv/employers/listings/check", json=other)
    assert r.status_code == 200, r.text
    assert "duplicate" not in [f["id"] for f in r.json()["check"]["flags"]]
