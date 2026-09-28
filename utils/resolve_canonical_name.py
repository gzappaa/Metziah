"""
utils/resolve_canonical_name.py

Canonical name resolution, v2.

Key change from v1: input now carries chain_id per candidate name, so we can
rank by "how many independent chains agree" instead of raw store-level votes.

Priority order (explicit, not multiplicative):
  1. Quality is a GATE, not a tiebreaker weight — junk/empty candidates are
     dropped before ranking, but a mediocre-but-valid name is never beaten
     by a "worse formula interaction".
  2. Among surviving candidates, cluster near-duplicates (same tokens,
     different order) using a sorted tuple.
  3. Rank clusters by (distinct_chain_count, total_votes) — chain breadth
     first, store-level frequency as the tiebreak.
  4. Within the winning cluster, return the single highest-quality raw string.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VOCABULARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "reference"
    / "canonical_name_vocabulary.json"
)

with VOCABULARY_PATH.open(encoding="utf-8") as f:
    CANONICAL_VOCABULARY = json.load(f)

CATEGORY_HINT_WORDS = set(
    CANONICAL_VOCABULARY["CATEGORY_HINT_WORDS"]
)

NON_IDENTITY_WORDS = set(
    CANONICAL_VOCABULARY["NON_IDENTITY_WORDS"]
)

UNITS_OF_MEASURE = set(
    CANONICAL_VOCABULARY["UNITS_OF_MEASURE"]
)

PRODUCT_INFO_HINT_WORDS = set(
    CANONICAL_VOCABULARY["PRODUCT_INFO_HINT_WORDS"]
)


JUNK_PATTERN = re.compile(r"^[\*\#\-\_\s]+")

SIZE_UNIT_PATTERN = re.compile(
    r"\d+(\.\d+)?\s*(ל|ליטר|מ\"ל|מל|גרם|ג|קג|ק\"ג)"
)

# Below this, a candidate is dropped entirely rather than ranked.
QUALITY_FLOOR = -5.0


def normalize_name(raw: str) -> str:
    """Normalize for comparison/scoring only — never stored/displayed."""
    if not raw:
        return ""

    s = re.sub(r"\s+", " ", raw.strip())
    s = JUNK_PATTERN.sub("", s).strip()

    return s


def token_key(name: str) -> tuple:
    """
    Order-independent, multiplicity-preserving cluster key.

    Sorted tuple rather than set means:
        X X Y != X Y
    """
    norm = normalize_name(name)

    tokens = [
        t.lower() if t.isascii() else t
        for t in norm.split(" ")
        if t
    ]

    return tuple(sorted(tokens))


def quality_score(raw: str) -> float:
    """
    Higher = cleaner/more complete.

    Quality is primarily used as a gate. Among names inside the winning
    cluster, it is also used to choose the best raw string.
    """
    if not raw or not raw.strip():
        return -100.0

    score = 0.0
    stripped = raw.strip()

    # Source formatting was sloppy.
    if JUNK_PATTERN.match(stripped):
        score -= 6.0

    norm = normalize_name(stripped)
    tokens = [t for t in norm.split(" ") if t]

    # Very short tokens can indicate truncated/abbreviated text.
    frag_tokens = [
        t for t in tokens
        if len(t) <= 2 and not t.isdigit()
    ]
    score -= 3.0 * len(frag_tokens)

    # Size + unit means the name carries concrete product information.
    if SIZE_UNIT_PATTERN.search(norm):
        score += 8.0

    # Product category information.
    if any(word in CATEGORY_HINT_WORDS for word in tokens):
        score += 4.0

    # Product-specific information:
    # flavor, state, dietary info, attributes, etc.
    if any(word in PRODUCT_INFO_HINT_WORDS for word in tokens):
        score += 4.0

    # Packaging/deposit metadata is deliberately neutral.
    # NON_IDENTITY_WORDS is kept as a separate vocabulary so it can be used
    # later if needed, but it does not currently affect quality.
    #
    # Example:
    #   "קולה 1.5 ליטר פיקדון"
    #
    # "פיקדון" does not make the name better or worse.

    length = len(norm)

    if length < 6:
        score -= 4.0
    elif length > 60:
        score -= 3.0
    else:
        score += 1.0

    return score


@dataclass
class NameCluster:
    key: tuple

    # raw_name -> {chain_id: count}
    names: dict = field(default_factory=dict)

    def add(self, raw_name: str, chain_counts: dict):
        bucket = self.names.setdefault(raw_name, {})

        for chain_id, count in chain_counts.items():
            bucket[chain_id] = bucket.get(chain_id, 0) + count

    @property
    def distinct_chain_count(self) -> int:
        chains = set()

        for chain_counts in self.names.values():
            chains.update(chain_counts.keys())

        return len(chains)

    @property
    def total_votes(self) -> int:
        return sum(
            sum(chain_counts.values())
            for chain_counts in self.names.values()
        )

    @property
    def best_name(self) -> str:
        """Within the winning cluster, choose the highest-quality raw name."""
        return max(
            self.names.keys(),
            key=quality_score,
        )


def resolve_canonical_name(name_chain_counts: dict) -> str:
    """
    Main entry point.

    Args:
        name_chain_counts:
            {
                raw_name: {
                    chain_id: store_count
                }
            }

    Returns:
        The chosen canonical raw name string, or "" if every candidate
        was filtered out.
    """
    if not name_chain_counts:
        return ""

    if len(name_chain_counts) == 1:
        return next(iter(name_chain_counts))

    # -----------------------------------------------------------------------
    # Step 1: quality gate
    # -----------------------------------------------------------------------

    survivors = {
        name: chain_counts
        for name, chain_counts in name_chain_counts.items()
        if quality_score(name) >= QUALITY_FLOOR
    }

    if not survivors:
        return ""

    if len(survivors) == 1:
        return next(iter(survivors))

    # -----------------------------------------------------------------------
    # Step 2: cluster near-duplicates
    # -----------------------------------------------------------------------

    clusters = {}

    for raw_name, chain_counts in survivors.items():
        key = token_key(raw_name)

        clusters.setdefault(
            key,
            NameCluster(key=key),
        ).add(
            raw_name,
            chain_counts,
        )

    # -----------------------------------------------------------------------
    # Step 3: rank clusters
    #
    # First: how many independent chains agree?
    # Second: how many total stores use those names?
    # -----------------------------------------------------------------------

    best_cluster = max(
        clusters.values(),
        key=lambda cluster: (
            cluster.distinct_chain_count,
            cluster.total_votes,
        ),
    )

    # -----------------------------------------------------------------------
    # Step 4: choose the best raw name inside the winning cluster
    # -----------------------------------------------------------------------

    return best_cluster.best_name


if __name__ == "__main__":

    # All candidates have one vote from one chain.
    # Therefore chain breadth is tied and quality decides.
    example = {
        "** קוקה קולה זירו בק": {"chain_A": 1},
        "ZERO קולה 1.5 ליטר פיקדון": {"chain_B": 1},
        "משקה קוקה קולה זירו": {"chain_C": 1},
        "קולה 1.5 ZERO ליטר פיקדון": {"chain_D": 1},
        "קולה 1.5 ליטר ZERO": {"chain_E": 1},
    }

    print(
        "Example 1:",
        resolve_canonical_name(example),
    )

    # Chain breadth beats raw store count.
    example2 = {
        "מוצר טוב עם גודל 1.5 ליטר": {
            "chain_A": 1,
            "chain_B": 1,
            "chain_C": 1,
        },
        "שם בינוני": {
            "chain_D": 900,
        },
    }

    print(
        "Example 2 (chain-breadth wins):",
        resolve_canonical_name(example2),
    )

    # All candidates are junk.
    example3 = {
        "**": {"chain_A": 1},
        "*": {"chain_B": 1},
    }

    print(
        "Example 3 (all junk):",
        repr(resolve_canonical_name(example3)),
    )