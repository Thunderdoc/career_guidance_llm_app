"""Geohash spatial index for the Kaam-Vaani listing radius filter (Step 8.3).

A worker in Madurai asking "jobs near me" should not have to know
which towns are within reach — the AI answers by distance, not by
exact city-name match. Listings carry a city name only (no street
address), so every listing is located at its city's centre and the
radius is city-centre to city-centre — approximate by design
(ASSUMPTIONS.md A57). Only the 6 cities the seed listings use have
coordinates (``data/kv_city_coords.yaml``, geocoded 21 Nov 2026);
listings in unmapped cities are excluded from radius results
(LIMITATIONS.md L57).

Design
-------
``GeohashIndex`` encodes every listing once (precision 6,
~1.2 km x 0.61 km cells) and keeps the ``(hash, item_id)`` pairs
sorted. A radius query:

1. picks a query precision from the radius (coarse for a wide
   radius, so the bounding box spans few cells),
2. enumerates the geohash cells intersecting the query disc's
   bounding box,
3. pulls each cell's entries with a binary-search prefix range
   (``bisect`` on the sorted hashes), and
4. filters the candidates with an exact haversine distance.

The geohash step only *prunes* — the haversine filter decides,
so a cell-boundary artefact can never include a listing outside
the radius or exclude one inside it. The property test
(``tests/test_kv_step8_3.py``) pins this: on seeded random data
the index agrees exactly with a linear scan at every radius.

Complexity (also in ARCHITECTURE.md section 7.7)
------------------------------------------------
Build: O(n log n) for the sort, O(n) space. Query: O(cells x
log n + candidates) haversines, where cells is the number of
bounding-box cells (up to ~500 in the 60 km band — the cells
are deliberately small relative to the radius, so the
candidate set stays close to the true result) and candidates
is the number of listings in those cells — versus O(n)
haversines for a linear scan. At pilot scale (tens of
listings) the index is overhead the benchmark still measures
(0.3x at 1k); at 10k+ listings it is the difference between a
fast filter and a full table scan (3.4x at 10k, 9.9x at 100k;
numbers in the plan doc).

The store still fetches verified rows from SQLite before the
index runs (pilot scale — a few hundred rows at most). Pushing
the geohash prefix into SQL is future work, noted in L57.
"""

from __future__ import annotations

import bisect
import math
from functools import lru_cache
from pathlib import Path
from typing import Generic, TypeVar

import yaml

T = TypeVar("T")

__all__ = [
    "GeohashIndex",
    "city_coords",
    "geohash_decode",
    "geohash_encode",
    "haversine_km",
    "load_city_coords",
    "mapped_cities",
]

COORDS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "kv_city_coords.yaml"

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_EARTH_RADIUS_KM = 6371.0
_KM_PER_DEGREE_LAT = 111.32

# (max radius for this band, query precision). The precision is
# chosen so the CELLS ARE SMALL relative to the radius: the
# dominant query cost is the haversine filter over the candidate
# set, and coarse cells inflate it — a first version used p3 for
# a 50 km radius and pulled ~56% of a 100k table into the filter
# (1.8x vs linear scan). With cells ~R/10 the bounding box stays
# close to the disc and the candidate set stays close to the true
# result. Cell sizes: p6 ~1.22 x 0.61 km, p5 ~4.9 x 4.9 km, p4
# ~39.1 x 19.5 km, p3 ~156 x 156 km.
_QUERY_PRECISION: tuple[tuple[float, int], ...] = (
    (5.0, 6),
    (60.0, 5),
    (150.0, 4),
    (float("inf"), 3),
)

_INDEX_PRECISION = 6


def geohash_encode(lat: float, lon: float, precision: int = 6) -> str:
    """Encode a point as a base32 geohash of ``precision`` characters.

    Bits alternate longitude / latitude, five bits per character.
    Raises ValueError on out-of-range coordinates or precision < 1.
    """
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude out of range: {lon}")
    if precision < 1:
        raise ValueError(f"precision must be >= 1, got {precision}")
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    bits = []
    even = True  # longitude bit first
    while len(bits) < precision * 5:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon >= mid:
                bits.append(1)
                lon_range[0] = mid
            else:
                bits.append(0)
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                bits.append(1)
                lat_range[0] = mid
            else:
                bits.append(0)
                lat_range[1] = mid
        even = not even
    out = []
    for i in range(0, len(bits), 5):
        value = 0
        for bit in bits[i : i + 5]:
            value = (value << 1) | bit
        out.append(_BASE32[value])
    return "".join(out)


def geohash_decode(hash_str: str) -> tuple[float, float, float, float]:
    """Decode a geohash to (centre lat, centre lon, lat error, lon error).

    The errors are half the cell's height / width in degrees: the
    cell spans [centre - error, centre + error] on each axis.
    """
    if not hash_str or any(ch not in _BASE32 for ch in hash_str):
        raise ValueError(f"not a geohash: {hash_str!r}")
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    even = True
    for ch in hash_str:
        value = _BASE32.index(ch)
        for shift in (4, 3, 2, 1, 0):
            bit = (value >> shift) & 1
            if even:
                mid = (lon_range[0] + lon_range[1]) / 2
                if bit:
                    lon_range[0] = mid
                else:
                    lon_range[1] = mid
            else:
                mid = (lat_range[0] + lat_range[1]) / 2
                if bit:
                    lat_range[0] = mid
                else:
                    lat_range[1] = mid
            even = not even
    lat = (lat_range[0] + lat_range[1]) / 2
    lon = (lon_range[0] + lon_range[1]) / 2
    return lat, lon, (lat_range[1] - lat_range[0]) / 2, (lon_range[1] - lon_range[0]) / 2


def _prefix_successor(prefix: str) -> str | None:
    """Smallest base32 string greater than every string starting with ``prefix``.

    Increments the last character that can carry (``'z'`` wraps to
    the previous character). Returns None when the prefix is all
    ``'z'`` — then the prefix range runs to the end of the list.
    """
    chars = list(prefix)
    for i in range(len(chars) - 1, -1, -1):
        idx = _BASE32.index(chars[i])
        if idx + 1 < len(_BASE32):
            chars[i] = _BASE32[idx + 1]
            return "".join(chars[: i + 1])
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres (earth radius 6371 km)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _query_precision(radius_km: float) -> int:
    for max_radius, precision in _QUERY_PRECISION:
        if radius_km <= max_radius:
            return precision
    return 2  # unreachable — the last band is infinite


def _bbox_cells(lat: float, lon: float, radius_km: float, precision: int) -> set[str]:
    """Geohash cells at ``precision`` intersecting the disc's bounding box.

    Grid points step by one full cell. That is safe only because
    of the padding: the box is padded by one full cell on every
    side, so a cell that only touches the true bounding box in a
    sliver still lies wholly inside the padded box — and a
    one-cell-wide interval always contains a point of a
    one-cell-spaced lattice. Without the padding, sliver cells
    fall between grid points and are missed (found by the
    property test — 13 of 60 random trials missed points before
    the padding). The box is clamped to the valid lat/lon range
    (no dateline wrap — the pilot is Tamil Nadu, far from it).
    """
    _, _, lat_err, lon_err = geohash_decode(geohash_encode(lat, lon, precision))
    lat_span = radius_km / _KM_PER_DEGREE_LAT
    lon_span = radius_km / (_KM_PER_DEGREE_LAT * max(math.cos(math.radians(lat)), 0.01))
    min_lat = max(-90.0, lat - lat_span - 2 * lat_err)
    max_lat = min(90.0, lat + lat_span + 2 * lat_err)
    min_lon = max(-180.0, lon - lon_span - 2 * lon_err)
    max_lon = min(180.0, lon + lon_span + 2 * lon_err)
    step_lat = max(2 * lat_err, 1e-9)  # one full cell
    step_lon = max(2 * lon_err, 1e-9)
    cells: set[str] = set()
    grid_lat = min_lat
    while grid_lat <= max_lat + 1e-9:
        grid_lon = min_lon
        while grid_lon <= max_lon + 1e-9:
            cells.add(geohash_encode(grid_lat, grid_lon, precision))
            grid_lon += step_lon
        grid_lat += step_lat
    return cells


@lru_cache(maxsize=1)
def load_city_coords() -> dict[str, tuple[float, float]]:
    """City-centre coordinates from ``data/kv_city_coords.yaml``.

    Keys are canonical city names; values are (lat, lon). Raises
    on a missing file or a malformed entry — a radius filter that
    silently runs on wrong coordinates is worse than one that
    refuses to start.
    """
    if not COORDS_PATH.exists():
        raise FileNotFoundError(f"city coordinates file not found: {COORDS_PATH}")
    data = yaml.safe_load(COORDS_PATH.read_text(encoding="utf-8")) or {}
    cities = data.get("cities") or {}
    if not isinstance(cities, dict) or not cities:
        raise ValueError(f"no cities in {COORDS_PATH}")
    coords: dict[str, tuple[float, float]] = {}
    for name, entry in cities.items():
        try:
            lat = float(entry["lat"])
            lon = float(entry["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bad coordinates for {name!r} in {COORDS_PATH}") from exc
        if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
            raise ValueError(f"coordinates out of range for {name!r} in {COORDS_PATH}")
        coords[str(name)] = (lat, lon)
    return coords


def city_coords(name: str) -> tuple[float, float] | None:
    """(lat, lon) for a city name, case-insensitive; None if unmapped."""
    wanted = name.strip().lower()
    for city, coords in load_city_coords().items():
        if city.lower() == wanted:
            return coords
    return None


def mapped_cities() -> list[str]:
    """Canonical names of the cities that have coordinates, sorted."""
    return sorted(load_city_coords())


class GeohashIndex(Generic[T]):
    """A sorted geohash index over (item_id, lat, lon) entries.

    Build once, query many times. ``within`` returns the item ids
    inside the radius; the order is unspecified — callers that
    need newest-first (or any order) sort the result themselves.
    Item ids are never compared (the bisect keys are one-tuples),
    so any hashable id type works.
    """

    def __init__(
        self, entries: list[tuple[T, float, float]], precision: int = _INDEX_PRECISION
    ) -> None:
        self._precision = precision
        self._entries: list[tuple[str, T]] = sorted(
            (geohash_encode(lat, lon, precision), item_id) for item_id, lat, lon in entries
        )
        self._coords: dict[T, tuple[float, float]] = {
            item_id: (lat, lon) for item_id, lat, lon in entries
        }

    def __len__(self) -> int:
        return len(self._entries)

    def within(self, lat: float, lon: float, radius_km: float) -> list[T]:
        """Item ids within ``radius_km`` of the point (haversine-exact)."""
        if radius_km <= 0:
            raise ValueError(f"radius_km must be > 0, got {radius_km}")
        if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
            raise ValueError(f"centre out of range: ({lat}, {lon})")
        precision = _query_precision(radius_km)
        candidates: set[str] = set()
        for cell in _bbox_cells(lat, lon, radius_km, precision):
            start = bisect.bisect_left(self._entries, (cell,))
            successor = _prefix_successor(cell)
            end = (
                bisect.bisect_left(self._entries, (successor,))
                if successor is not None
                else len(self._entries)
            )
            candidates.update(item_id for _, item_id in self._entries[start:end])
        return [
            item_id
            for item_id in candidates
            if haversine_km(lat, lon, *self._coords[item_id]) <= radius_km
        ]
