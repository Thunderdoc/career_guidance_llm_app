"""Near-duplicate detection for Kaam-Vaani listings (Step 8.4).

The same job posted twice — by accident or to game the board —
should be caught when the employer submits it, not left for an
admin to spot. The old check (Stage 5, L42) matched only an
exact normalised title in the same city for the same employer:
it missed reworded reposts, and it wrongly flagged a genuinely
new opening that reused a title ("Store keeper", twice, for two
different roles).

Three layers, in the order they run:

1. **Exact hash.** SHA-256 over the normalised
   title + city + description. An identical repost matches with
   similarity 1.0.
2. **Bloom filter.** A Bloom filter over the exact hashes is the
   pre-filter for the exact lookup: "definitely not present"
   skips the dict lookup, "possibly present" is confirmed by
   the dict (so a Bloom false positive can never flag a
   listing — it only costs one dict lookup). Sized for 10,000
   listings at a 1% design false-positive rate; the measured
   rate on the seed data is in the plan doc. At pilot scale
   (45 listings) the filter is a validated component, not a
   bottleneck fix — the honest scaling story is in
   ARCHITECTURE.md section 7.8.
3. **Shingle Jaccard.** Word 3-shingles over the normalised
   title + description (the shingle size adapts down when the
   text is shorter than 3 words), Jaccard similarity against
   the same employer's listings in the same city. A similarity
   at or above ``JACCARD_THRESHOLD`` is a near-duplicate. The
   threshold was tuned on a labelled set (real seed listings +
   synthetic near-duplicates, labelled honestly) — see the plan
   doc for the precision/recall table.

Scope (unchanged from L42): same employer, same city. A
different employer posting the same text is cross-employer
duplication — an admin judgement, not an automatic block. The
detector returns the best match (exact first, then the highest
similarity, most recent on a tie); the scam check turns any
match into its 25-point ``duplicate`` flag.

Complexity (also in ARCHITECTURE.md section 7.8): building the
index is O(L x W) for L listings of W words (shingle sets);
an exact lookup is O(k) Bloom hashes + O(1) dict; a near lookup
is O(E x S) Jaccard comparisons against the employer's E
listings in the city with S shingles each. The index is cached
on the store and invalidated by every listing write.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

__all__ = [
    "JACCARD_THRESHOLD",
    "BloomFilter",
    "DuplicateIndex",
    "DuplicateMatch",
    "jaccard",
    "listing_fingerprint",
    "normalize_text",
    "text_shingles",
]

# Tuned on the labelled set (369 pairs: 279 positive, 90
# negative — see the plan doc for the full sweep). Precision is
# 1.000 at every threshold from 0.3 to 0.9 (the highest negative
# scores 0.111); 0.5 keeps a 0.389 margin above that while
# catching 90.7% of reworded reposts (recall 0.982 at 0.3, but
# only 0.189 above the highest negative — too close for a
# production threshold on a 90-negative sample). The 26 misses
# at 0.5 are the heavily edited variants (title AND description
# both changed, similarity 0.125–0.5).
JACCARD_THRESHOLD = 0.5

# Bloom filter sizing: 10,000 listings at a 1% design FP rate.
_BLOOM_EXPECTED_ITEMS = 10_000
_BLOOM_FP_RATE = 0.01

_WORDS = re.compile(r"\w+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip. The single normaliser
    for fingerprints and shingles, so both layers agree on what
    "the same text" means."""
    return " ".join(text.lower().split())


def listing_fingerprint(title: str, description: str, city: str) -> str:
    """SHA-256 over normalised title + city + description."""
    payload = "\n".join((normalize_text(title), normalize_text(city), normalize_text(description)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_shingles(text: str, n: int = 3) -> set[str]:
    """Word n-shingles over the normalised text. The shingle size
    adapts down when the text is shorter than ``n`` words (a
    two-word title still yields one 2-shingle); empty text yields
    no shingles."""
    words = _WORDS.findall(normalize_text(text))
    if not words:
        return set()
    size = min(n, len(words))
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity. Either side empty means no evidence of
    similarity (0.0) — two empty texts are not a duplicate, they
    are two empty submissions."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class BloomFilter:
    """A Bloom filter over strings, with double hashing.

    ``sized_for`` computes the optimal bit count and hash count
    for an expected item count and target false-positive rate.
    ``theoretical_fp_rate`` reports the expected rate for the
    items actually inserted.
    """

    def __init__(self, num_bits: int, num_hashes: int) -> None:
        if num_bits < 8:
            raise ValueError(f"num_bits must be >= 8, got {num_bits}")
        if num_hashes < 1:
            raise ValueError(f"num_hashes must be >= 1, got {num_hashes}")
        self.num_bits = num_bits
        self.num_hashes = num_hashes
        self._bits = bytearray((num_bits + 7) // 8)
        self.inserted = 0

    @classmethod
    def sized_for(cls, expected_items: int, fp_rate: float) -> BloomFilter:
        if expected_items < 1:
            raise ValueError("expected_items must be >= 1")
        if not 0 < fp_rate < 1:
            raise ValueError("fp_rate must be between 0 and 1")
        num_bits = max(8, math.ceil(-expected_items * math.log(fp_rate) / (math.log(2) ** 2)))
        num_hashes = max(1, round((num_bits / expected_items) * math.log(2)))
        return cls(num_bits, num_hashes)

    def _positions(self, item: str) -> list[int]:
        digest = hashlib.sha256(item.encode("utf-8")).digest()
        h1 = int.from_bytes(digest[:8], "big")
        h2 = int.from_bytes(digest[8:16], "big") | 1  # odd, so all k positions differ
        return [(h1 + i * h2) % self.num_bits for i in range(self.num_hashes)]

    def add(self, item: str) -> None:
        for pos in self._positions(item):
            self._bits[pos // 8] |= 1 << (pos % 8)
        self.inserted += 1

    def __contains__(self, item: str) -> bool:
        return all(self._bits[pos // 8] & (1 << (pos % 8)) for pos in self._positions(item))

    def theoretical_fp_rate(self) -> float:
        """(1 - e^(-k n / m))^k for the items actually inserted."""
        if self.inserted == 0:
            return 0.0
        fill = 1 - math.exp(-self.num_hashes * self.inserted / self.num_bits)
        return fill**self.num_hashes


@dataclass(frozen=True)
class DuplicateMatch:
    """A duplicate found by the index: which listing, how, and how
    similar. ``method`` is ``"exact"`` (identical fingerprint,
    similarity 1.0) or ``"near"`` (shingle Jaccard >= threshold)."""

    listing_id: int
    method: str
    similarity: float


@dataclass
class _Entry:
    listing_id: int
    employer_id: int
    city: str
    fingerprint: str
    shingles: set[str]
    created_at: str


class DuplicateIndex:
    """Exact-hash + Bloom + shingle index over listings.

    Built once from listing rows (any status — a repost of a
    pending listing is still a duplicate) and queried per
    submission. ``find`` is scoped to one employer and one city.
    """

    def __init__(self, rows: list[tuple[int, int, str, str, str, str]]) -> None:
        """``rows`` are (listing_id, employer_id, title,
        description, city, created_at)."""
        self._by_fingerprint: dict[str, list[_Entry]] = {}
        self._entries: list[_Entry] = []
        self.bloom = BloomFilter.sized_for(_BLOOM_EXPECTED_ITEMS, _BLOOM_FP_RATE)
        for listing_id, employer_id, title, description, city, created_at in rows:
            fingerprint = listing_fingerprint(title, description, city)
            entry = _Entry(
                listing_id=listing_id,
                employer_id=employer_id,
                city=normalize_text(city),
                fingerprint=fingerprint,
                shingles=text_shingles(f"{title} {description}"),
                created_at=created_at,
            )
            self._entries.append(entry)
            self._by_fingerprint.setdefault(fingerprint, []).append(entry)
            self.bloom.add(fingerprint)

    def __len__(self) -> int:
        return len(self._entries)

    def find(
        self,
        employer_id: int,
        title: str,
        description: str,
        city: str,
        exclude_id: int | None = None,
    ) -> DuplicateMatch | None:
        """The best duplicate for a candidate listing, or None.

        Exact matches win over near ones; among near matches the
        highest similarity wins, most recent on a tie.
        """
        fingerprint = listing_fingerprint(title, description, city)
        if fingerprint in self.bloom:
            for entry in self._by_fingerprint.get(fingerprint, []):
                if (
                    entry.employer_id == employer_id
                    and entry.city == normalize_text(city)
                    and entry.listing_id != exclude_id
                ):
                    return DuplicateMatch(entry.listing_id, "exact", 1.0)
        candidate_shingles = text_shingles(f"{title} {description}")
        best: DuplicateMatch | None = None
        best_created = ""
        for entry in self._entries:
            if (
                entry.employer_id != employer_id
                or entry.city != normalize_text(city)
                or entry.listing_id == exclude_id
            ):
                continue
            similarity = jaccard(candidate_shingles, entry.shingles)
            if similarity < JACCARD_THRESHOLD:
                continue
            if (
                best is None
                or similarity > best.similarity
                or (similarity == best.similarity and entry.created_at > best_created)
            ):
                best = DuplicateMatch(entry.listing_id, "near", similarity)
                best_created = entry.created_at
        return best
