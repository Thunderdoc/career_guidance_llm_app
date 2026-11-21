"""Kaam-Vaani Step 8.3: geohash location index + radius filter.

Covers: the geohash encoder/decoder (including the Wikipedia
reference vector), haversine distances, the city-coordinates file,
the index-vs-linear-scan property (exact agreement on seeded
random data at every radius), the store radius search (nearby-only
results, default radius, unknown-city/conflict errors, unmapped
cities excluded, newest-first order + limit-after-filter, cache
invalidation on every listing write), and the router end to end.
"""

from __future__ import annotations

import random

import pytest

from career_guidance.kaamvaani.employers import EmployerStore
from career_guidance.kaamvaani.geo import (
    GeohashIndex,
    _prefix_successor,
    city_coords,
    geohash_decode,
    geohash_encode,
    haversine_km,
    mapped_cities,
)
from career_guidance.migrations import migrate

MADURAI = (9.92422, 78.12418)
CHENNAI = (13.08404, 80.28274)
VIRUDHUNAGAR = (9.58919, 77.95368)
SEED_CITIES = ["Chennai", "Dindigul", "Madurai", "Tirunelveli", "Tiruppur", "Virudhunagar"]


# --------------------------------------------------------------------------- #
# Geohash encode / decode
# --------------------------------------------------------------------------- #


def test_encode_matches_reference_vector():
    # The Wikipedia geohash example: (57.64911, 10.40744) -> u4pruydqqvj.
    assert geohash_encode(57.64911, 10.40744, 11) == "u4pruydqqvj"


def test_decode_roundtrip_contains_point():
    points = [MADURAI, CHENNAI, VIRUDHUNAGAR, (0.0, 0.0), (-33.9, 151.2)]
    for lat, lon in points:
        for precision in (3, 6, 9):
            lat_c, lon_c, lat_err, lon_err = geohash_decode(geohash_encode(lat, lon, precision))
            assert abs(lat_c - lat) <= lat_err
            assert abs(lon_c - lon) <= lon_err
    # Error bounds shrink with precision.
    _, _, err3, _ = geohash_decode(geohash_encode(*MADURAI, 3))
    _, _, err6, _ = geohash_decode(geohash_encode(*MADURAI, 6))
    _, _, err9, _ = geohash_decode(geohash_encode(*MADURAI, 9))
    assert err3 > err6 > err9


def test_encode_decode_validation():
    with pytest.raises(ValueError, match="latitude"):
        geohash_encode(91.0, 0.0)
    with pytest.raises(ValueError, match="longitude"):
        geohash_encode(0.0, 181.0)
    with pytest.raises(ValueError, match="precision"):
        geohash_encode(0.0, 0.0, 0)
    with pytest.raises(ValueError, match="not a geohash"):
        geohash_decode("abci")  # 'i' is not in the base32 alphabet
    with pytest.raises(ValueError, match="not a geohash"):
        geohash_decode("")


def _common_prefix(a: str, b: str) -> int:
    length = 0
    for x, y in zip(a, b, strict=True):
        if x != y:
            break
        length += 1
    return length


def test_prefix_property_near_vs_far():
    near = geohash_encode(MADURAI[0] + 0.001, MADURAI[1] + 0.001, 6)
    base = geohash_encode(*MADURAI, 6)
    far = geohash_encode(*CHENNAI, 6)
    assert _common_prefix(near, base) >= 4
    assert _common_prefix(far, base) <= 1


def test_prefix_successor():
    assert _prefix_successor("abc") == "abd"
    assert _prefix_successor("abz") == "ac"  # carry
    assert _prefix_successor("zzz") is None


# --------------------------------------------------------------------------- #
# Haversine + city coordinates
# --------------------------------------------------------------------------- #


def test_haversine_known_distances():
    # Bands, not exact figures: the inputs are city-centre points,
    # so the check is that the formula is in the right order of
    # magnitude (a degrees/radians mixup would be off by ~50x).
    assert 400 < haversine_km(*MADURAI, *CHENNAI) < 450
    assert 35 < haversine_km(*MADURAI, *VIRUDHUNAGAR) < 50
    assert haversine_km(*MADURAI, *MADURAI) == 0.0
    assert haversine_km(*MADURAI, *CHENNAI) == haversine_km(*CHENNAI, *MADURAI)


def test_all_seed_cities_mapped():
    assert mapped_cities() == SEED_CITIES
    assert city_coords("Madurai") == pytest.approx(MADURAI)
    assert city_coords("Chennai") == pytest.approx(CHENNAI)
    assert city_coords("Virudhunagar") == pytest.approx(VIRUDHUNAGAR)


def test_city_coords_case_insensitive_and_unknown():
    assert city_coords("madurai") == pytest.approx(MADURAI)
    assert city_coords("  Tiruppur ") is not None
    assert city_coords("Coimbatore") is None  # in the vocab, not mapped (L57)


# --------------------------------------------------------------------------- #
# Index vs linear scan (property)
# --------------------------------------------------------------------------- #


def test_index_matches_linear_scan():
    rng = random.Random(42)
    entries = [(f"p{i}", rng.uniform(8.0, 13.5), rng.uniform(76.0, 80.5)) for i in range(2000)]
    index = GeohashIndex(entries)
    for _ in range(40):
        lat = rng.uniform(8.0, 13.5)
        lon = rng.uniform(76.0, 80.5)
        radius = rng.choice([1, 5, 10, 25, 50, 100, 150])
        got = set(index.within(lat, lon, radius))
        want = {item_id for item_id, la, lo in entries if haversine_km(lat, lon, la, lo) <= radius}
        assert got == want, f"mismatch at radius {radius}"


def test_index_empty_and_single():
    empty = GeohashIndex([])
    assert empty.within(*MADURAI, 50) == []
    assert len(empty) == 0
    single = GeohashIndex([("only", *VIRUDHUNAGAR)])
    assert single.within(*MADURAI, 50) == ["only"]  # 41.7 km away
    assert single.within(*MADURAI, 25) == []
    assert single.within(*CHENNAI, 50) == []


def test_index_validation():
    index = GeohashIndex([("a", *MADURAI)])
    with pytest.raises(ValueError, match="radius_km"):
        index.within(*MADURAI, 0)
    with pytest.raises(ValueError, match="radius_km"):
        index.within(*MADURAI, -5)
    with pytest.raises(ValueError, match="out of range"):
        index.within(91.0, 0.0, 10)


# --------------------------------------------------------------------------- #
# Store radius search
# --------------------------------------------------------------------------- #


def _store(tmp_path, name="kv83.db") -> EmployerStore:
    path = str(tmp_path / name)
    migrate(path)
    return EmployerStore(path)


def _verified_listing(store, employer_id, city, title):
    listing = store.create_listing(
        employer_id,
        title=title,
        role_category="general",
        description=f"Work in {city}.",
        city=city,
        district=city,
    )
    return store.set_listing_status(listing.id, "verified", reviewer="admin")


def _seed_cities(store):
    employer = store.create_employer(
        "u-emp",
        business_name="Test Shop",
        contact_name="Tester",
        city="Madurai",
        district="Madurai",
        business_type="Shop",
        description="Test employer.",
    )
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    listings = {}
    for city in SEED_CITIES:
        listings[city] = _verified_listing(store, employer.id, city, f"Helper in {city}")
    return listings


def test_radius_search_finds_nearby_only(tmp_path):
    store = _store(tmp_path)
    listings = _seed_cities(store)
    found = store.list_public_listings(near_city="Madurai", radius_km=50)
    found_cities = {item.city for item in found}
    # Property form: every returned city is within 50 km of Madurai,
    # and every seeded city within 50 km is returned (Dindigul at
    # 51.5 km sits just outside — the assertion does not hardcode it).
    for city in found_cities:
        assert haversine_km(*MADURAI, *city_coords(city)) <= 50
    for city in SEED_CITIES:
        if haversine_km(*MADURAI, *city_coords(city)) <= 50:
            assert city in found_cities
    assert listings["Madurai"].id in [item.id for item in found]
    assert listings["Chennai"].id not in [item.id for item in found]


def test_radius_default_25km(tmp_path):
    store = _store(tmp_path)
    _seed_cities(store)
    found = store.list_public_listings(near_city="Madurai")
    # Virudhunagar (41.7 km) is outside the 25 km default.
    assert {item.city for item in found} == {"Madurai"}


def test_radius_validation_errors(tmp_path):
    store = _store(tmp_path)
    _seed_cities(store)
    with pytest.raises(ValueError, match="not both"):
        store.list_public_listings(city="Madurai", near_city="Madurai")
    with pytest.raises(ValueError, match="needs near_city"):
        store.list_public_listings(radius_km=50)
    with pytest.raises(ValueError, match="between 0 and 500"):
        store.list_public_listings(near_city="Madurai", radius_km=0)
    with pytest.raises(ValueError, match="between 0 and 500"):
        store.list_public_listings(near_city="Madurai", radius_km=600)
    with pytest.raises(ValueError, match="No coordinates for 'Coimbatore'"):
        store.list_public_listings(near_city="Coimbatore")
    with pytest.raises(ValueError, match="Madurai"):
        store.list_public_listings(near_city="Coimbatore")


def test_radius_excludes_unmapped_city_but_city_filter_keeps_it(tmp_path):
    store = _store(tmp_path)
    listings = _seed_cities(store)
    employer_id = listings["Madurai"].employer_id
    unmapped = _verified_listing(store, employer_id, "Coimbatore", "Helper in Coimbatore")
    found = store.list_public_listings(near_city="Madurai", radius_km=500)
    assert unmapped.id not in [item.id for item in found]
    by_city = store.list_public_listings(city="Coimbatore")
    assert [item.id for item in by_city] == [unmapped.id]


def test_radius_keeps_newest_first_and_limit_after_filter(tmp_path):
    store = _store(tmp_path)
    employer = store.create_employer(
        "u-emp",
        business_name="Test Shop",
        contact_name="Tester",
        city="Madurai",
        district="Madurai",
        business_type="Shop",
        description="Test employer.",
    )
    store.set_employer_status(employer.id, "verified", reviewer="admin")
    madurai_ids = [
        _verified_listing(store, employer.id, "Madurai", f"Madurai job {i}").id for i in range(3)
    ]
    _verified_listing(store, employer.id, "Chennai", "Chennai job")
    found = store.list_public_listings(near_city="Madurai", radius_km=50, limit=2)
    # Newest first, and the limit applies after the radius filter:
    # two Madurai listings, never the Chennai one.
    assert [item.id for item in found] == madurai_ids[::-1][:2]


def test_geo_index_cache_invalidated_on_writes(tmp_path):
    store = _store(tmp_path)
    listings = _seed_cities(store)
    employer_id = listings["Madurai"].employer_id
    assert store._geo_index is None
    store.list_public_listings(near_city="Madurai", radius_km=50)
    assert store._geo_index is not None
    # Create + verify a new Madurai listing: it must appear.
    new = _verified_listing(store, employer_id, "Madurai", "New Madurai job")
    assert store._geo_index is None  # create invalidated the cache
    found = store.list_public_listings(near_city="Madurai", radius_km=50)
    assert new.id in [item.id for item in found]
    # Edit a verified listing: it drops to pending and disappears.
    store.update_listing(new.id, title="Edited title")
    found = store.list_public_listings(near_city="Madurai", radius_km=50)
    assert new.id not in [item.id for item in found]
    # Re-verify it: it comes back (set_listing_status invalidates).
    store.set_listing_status(new.id, "verified", reviewer="admin")
    found = store.list_public_listings(near_city="Madurai", radius_km=50)
    assert new.id in [item.id for item in found]
    # Delete it: gone for good.
    assert store.delete_listing(new.id) is True
    found = store.list_public_listings(near_city="Madurai", radius_km=50)
    assert new.id not in [item.id for item in found]


def test_plain_city_filter_unchanged(tmp_path):
    store = _store(tmp_path)
    listings = _seed_cities(store)
    assert [item.id for item in store.list_public_listings(city="Madurai")] == [
        listings["Madurai"].id
    ]
    assert len(store.list_public_listings()) == len(SEED_CITIES)


# --------------------------------------------------------------------------- #
# Router end to end
# --------------------------------------------------------------------------- #


def _seed_via_api_db(client, tmp_path):
    """Seed the client's own DB file directly (the app's geo index
    builds lazily on the first radius query, so it picks these up)."""
    path = str(tmp_path / "app.db")
    migrate(path)
    store = EmployerStore(path)
    return _seed_cities(store)


def test_router_radius_search(client, tmp_path):
    listings = _seed_via_api_db(client, tmp_path)
    r = client.get("/api/v1/kv/listings?near_city=Madurai&radius_km=50")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["near_city"] == "Madurai"
    assert body["radius_km"] == 50
    ids = [item["id"] for item in body["listings"]]
    assert listings["Madurai"].id in ids
    assert listings["Chennai"].id not in ids
    # Default radius echoes 25 km.
    r = client.get("/api/v1/kv/listings?near_city=Madurai")
    assert r.status_code == 200, r.text
    assert r.json()["radius_km"] == 25.0


def test_router_radius_errors(client, tmp_path):
    _seed_via_api_db(client, tmp_path)
    r = client.get("/api/v1/kv/listings?near_city=Coimbatore")
    assert r.status_code == 400, r.text
    assert "Coimbatore" in r.json()["detail"]
    r = client.get("/api/v1/kv/listings?city=Madurai&near_city=Madurai")
    assert r.status_code == 400, r.text
    r = client.get("/api/v1/kv/listings?radius_km=50")
    assert r.status_code == 400, r.text
    r = client.get("/api/v1/kv/listings?near_city=Madurai&radius_km=0")
    assert r.status_code == 400, r.text
    r = client.get("/api/v1/kv/listings?near_city=Madurai&radius_km=600")
    assert r.status_code == 400, r.text
