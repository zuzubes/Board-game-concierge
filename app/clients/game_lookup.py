"""Fast game name -> BGG ID resolution over the local masterlist CSV.

Avoids hitting the BGG API just to resolve an ID (see risk: BGG XML API
flakiness/rate limits in the project plan).
"""

from __future__ import annotations

import csv
import re
from difflib import get_close_matches
from functools import lru_cache

from app.config import MASTERLIST_CSV


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


_QUERY_PREFIXES = [
    r"^(?:rules?\s+(?:of|for)\s+)",
    r"^(?:rulebook\s+(?:for|of)\s+)",
    r"^(?:how\s+to\s+play\s+)",
    r"^(?:how\s+do\s+i\s+play\s+)",
    r"^(?:how\s+do\s+you\s+play\s+)",
    r"^(?:help\s+)",
    r"^(?:rules?\s+)",
]


def _normalize_query_candidates(query: str) -> list[str]:
    normalized = _normalize(query)
    candidates = [normalized]

    current = normalized
    changed = True
    while changed:
        changed = False
        for pattern in _QUERY_PREFIXES:
            stripped = re.sub(pattern, "", current).strip()
            if stripped and stripped != current and stripped not in candidates:
                candidates.append(stripped)
                current = stripped
                changed = True
                break

    return candidates


def _rank_value(row: dict) -> float:
    """Lower is better, unranked sorts last. BGG uses rank "0" as its
    unranked marker (not #1) - it's on ~83% of rows in this dataset, so
    without this an obscure unranked reprint sharing a name with a
    well-known game (e.g. a regional "Monopoly" variant vs. the original)
    would win the name-resolution tie-break just for having a numerically
    smaller rank string."""
    try:
        rank = int(row["rank"])
    except (ValueError, TypeError):
        return float("inf")
    return rank if rank > 0 else float("inf")


@lru_cache(maxsize=1)
def _load_index() -> dict[str, dict]:
    by_normalized_name: dict[str, dict] = {}
    with open(MASTERLIST_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = _normalize(row["name"])
            existing = by_normalized_name.get(key)
            if existing is None or _rank_value(row) < _rank_value(existing):
                by_normalized_name[key] = row
    return by_normalized_name


def resolve_game(query: str) -> dict | None:
    """Best-effort match of free text (e.g. "we're playing Wingspan tonight")
    to a masterlist row. Returns the CSV row dict, or None if nothing matches.
    """
    index = _load_index()
    normalized_queries = _normalize_query_candidates(query)

    if len(normalized_queries) > 1:
        prioritized_queries = normalized_queries[1:] + normalized_queries[:1]
    else:
        prioritized_queries = normalized_queries

    for normalized_query in prioritized_queries:
        if normalized_query in index:
            return index[normalized_query]

        # Padded with boundary spaces so matches only count on whole-word
        # boundaries - a plain substring check would let e.g. "Re:Play"
        # (normalizes to "re play") false-match inside "we aRE PLAYing risk
        # tonight", since "re play" is a raw character substring spanning across
        # "are"/"playing" even though neither word actually appears there.
        padded_query = f" {normalized_query} "
        candidates = [
            name for name in index
            if name and (f" {name} " in padded_query or padded_query in f" {name} ")
        ]
        if candidates:
            candidates.sort(key=len, reverse=True)
            return index[candidates[0]]

        close = get_close_matches(normalized_query, index.keys(), n=1, cutoff=0.7)
        if close:
            return index[close[0]]

    return None
