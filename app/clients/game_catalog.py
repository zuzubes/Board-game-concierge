"""Local CSV-backed game catalog for /recommend - no live API involved.

Combines masterlist/games.csv (broad coverage: player count, complexity,
age, ratings, category flags) with masterlist/bgg_db_2018_01.csv (narrower
top-5000 coverage, but adds real mechanic tags and clean min-max playtime),
masterlist/BGG_Data_Set.csv (broader ~20k-game mechanics coverage, used only
to fill mechanic tags for games outside bgg_db_2018's top-5000 - its age/
weight/rating columns were checked and add no games.csv doesn't already
have, so those aren't used), and masterlist/boardgames_ranks.csv (used here
only for its is_expansion flag, to keep expansions out of recommendation
candidates).
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache

from app.config import BGG_DATASET_CSV, BGG_DB_CSV, GAMES_CSV, MASTERLIST_CSV

CANDIDATE_POOL_SIZE = 25

CATEGORY_LABELS = {
    "Cat:Thematic": "Thematic",
    "Cat:Strategy": "Strategy",
    "Cat:War": "War",
    "Cat:Family": "Family",
    "Cat:CGS": "Card-driven",
    "Cat:Abstract": "Abstract",
    "Cat:Party": "Party",
    "Cat:Childrens": "Children's",
}


def _to_float(value: str | None) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _load_expansion_ids() -> dict[str, bool]:
    """id -> is_expansion, sourced from boardgames_ranks.csv (games.csv has
    no is_expansion column of its own)."""
    expansions: dict[str, bool] = {}
    with open(MASTERLIST_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            expansions[row["id"]] = row.get("is_expansion") == "1"
    return expansions


@lru_cache(maxsize=1)
def _load_enrichment() -> dict[str, dict]:
    """game_id -> {min_time, max_time, mechanics, categories}, sourced from
    bgg_db_2018_01.csv (top-5000 games as of Jan 2018 - narrower coverage
    than games.csv, but the only source of real mechanic tags and clean
    playtime ranges in this repo)."""
    enrichment: dict[str, dict] = {}
    # This file isn't valid UTF-8 (has raw Windows-1252/Latin-1 bytes in a
    # few designer names) - latin-1 never raises on any byte value, which is
    # good enough here since we only use the mechanic/category/time columns.
    with open(BGG_DB_CSV, newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f):
            mechanics = [m.strip() for m in (row.get("mechanic") or "").split(",") if m.strip()]
            categories = [c.strip() for c in (row.get("category") or "").split(",") if c.strip()]
            enrichment[row["game_id"]] = {
                "min_time": _to_int(row.get("min_time")),
                "max_time": _to_int(row.get("max_time")),
                "mechanics": mechanics,
                "categories": categories,
            }
    return enrichment


@lru_cache(maxsize=1)
def _load_bgg_dataset_mechanics() -> dict[str, list[str]]:
    """game_id -> mechanics, sourced from BGG_Data_Set.csv - a fallback for
    the ~17k games bgg_db_2018_01.csv's top-5000 cutoff leaves without any
    mechanic tags."""
    mechanics: dict[str, list[str]] = {}
    # Same non-UTF-8 byte issue as bgg_db_2018_01.csv - latin-1 to avoid
    # raising on it.
    with open(BGG_DATASET_CSV, newline="", encoding="latin-1") as f:
        for row in csv.DictReader(f):
            tags = [m.strip() for m in (row.get("Mechanics") or "").split(",") if m.strip()]
            if tags:
                mechanics[row["ID"]] = tags
    return mechanics


@lru_cache(maxsize=1)
def _load_games() -> list[dict]:
    """Parsed + typed games.csv rows, expansions excluded, enriched with
    bgg_db_2018_01.csv data where available. Loaded and cached once per
    process (~21.9k rows)."""
    expansion_ids = _load_expansion_ids()
    enrichment = _load_enrichment()
    fallback_mechanics = _load_bgg_dataset_mechanics()

    games: list[dict] = []
    with open(GAMES_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bgg_id = row["BGGId"]
            if expansion_ids.get(bgg_id, False):
                continue

            min_players = _to_int(row["MinPlayers"])
            max_players = _to_int(row["MaxPlayers"])
            if min_players is None or max_players is None:
                continue

            weight = _to_float(row["GameWeight"])
            age = _to_float(row["ComAgeRec"])
            if age is None:
                age = _to_float(row["MfgAgeRec"])

            enrich = enrichment.get(bgg_id, {})
            min_time = enrich.get("min_time") or _to_int(row["ComMinPlaytime"])
            max_time = (
                enrich.get("max_time")
                or _to_int(row["ComMaxPlaytime"])
                or _to_int(row["MfgPlaytime"])
            )

            categories = [
                label for col, label in CATEGORY_LABELS.items() if row[col] == "1"
            ]

            games.append({
                "bgg_id": bgg_id,
                "name": row["Name"],
                "description": row["Description"],
                "min_players": min_players,
                "max_players": max_players,
                "weight": weight if weight else None,  # 0.0 means "no data"
                "age": round(age) if age is not None else None,
                "avg_rating": _to_float(row["AvgRating"]),
                "bayes_rating": _to_float(row["BayesAvgRating"]),
                "min_time": min_time,
                "max_time": max_time,
                "mechanics": enrich.get("mechanics") or fallback_mechanics.get(bgg_id, []),
                "categories": categories,
            })
    return games


def find_candidates(player_count: int, limit: int = CANDIDATE_POOL_SIZE) -> list[dict]:
    """Games playable at player_count, non-expansion, sorted by BayesAvgRating
    (BGG's confidence-weighted quality signal - better than raw AvgRating
    since it already discounts games with few ratings), capped to `limit`."""
    return find_candidates_with_rating(player_count, None, limit=limit)


def find_candidates_with_rating(
    player_count: int,
    min_bgg_rating: float | None,
    limit: int = CANDIDATE_POOL_SIZE,
) -> list[dict]:
    matches = [
        g for g in _load_games()
        if g["min_players"] <= player_count <= g["max_players"]
        and (min_bgg_rating is None or (g["bayes_rating"] is not None and g["bayes_rating"] >= min_bgg_rating))
    ]
    matches.sort(
        key=lambda g: g["bayes_rating"] if g["bayes_rating"] is not None else -1,
        reverse=True,
    )
    return matches[:limit]


_PLAYER_COUNT_PATTERNS = [
    re.compile(
        r"\b(?:for|with|at|about)\s+(?:a\s+group\s+of\s+)?(\d{1,2})\s*"
        r"(?:players?|people|ppl|adults?|kids?|children|gamers?|persons?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,2})\s*(?:players?|people|ppl|adults?|kids?|children|gamers?|persons?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{1,2})\s*[- ]?player(?:s)?\b", re.IGNORECASE),
]


def extract_player_count(preferences: str) -> int | None:
    """Best-effort extraction of a player count from free text (e.g. "4
    people" or "for 4 players" or just "4"). Simple heuristic, not a full
    NLU parse - prefers numbers attached to player/count words and skips
    obvious rating mentions before falling back to a bare number. Acceptable
    for v1's single-message, no-session-state approach."""
    for pattern in _PLAYER_COUNT_PATTERNS:
        match = pattern.search(preferences)
        if match:
            return int(match.group(1))

    matches = [m for m in re.finditer(r"\b(\d{1,2})\b", preferences)]
    for match in matches:
        start, end = match.span(1)
        left = preferences[max(0, start - 10):start].casefold()
        right = preferences[end:min(len(preferences), end + 10)].casefold()
        if "rating" in left or "rating" in right or "+" in right:
            continue
        return int(match.group(1))

    return None
