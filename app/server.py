"""FastAPI service: the Board Game Concierge's RAG endpoints.

/report     - initial pre-session digest for a game, triggered by a Telegram
              command like "we're playing Wingspan tonight"
/ask        - one grounded follow-up question in the same chat session
/recommend  - a game recommendation for a stated player count/preferences

BGG's XML API and Reddit's Data API are out of consideration entirely - both
now require registration/approval we don't have and aren't pursuing. All
content here is grounded in either the imported rulebook PDFs or the local
masterlist CSVs, plus the LLM's own general knowledge where the persona
already allows that (strategy tips, "plays like X" comparisons).
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from pydantic import BaseModel

from app.clients.game_catalog import extract_player_count, find_candidates_with_rating
from app.clients.game_lookup import find_direct_game_mentions, resolve_game
from app.clients.tips_client import TipServiceUnavailable, get_tip
from app.config import PILOT_GAMES_BY_BGG_ID
from app.formatting import to_plain_text
from app.memory import (
    clear_pending,
    clear_session,
    get_pending,
    get_session_game,
    remember_pending,
    remember_report,
)
from app.phrasing import greeting, pick_variant
from app.rag.vectorstore import retrieve_digest_chunks, retrieve_followup_chunks
from app.synthesis import build_followup_answer, build_recommendation, build_report, build_tip

app = FastAPI(title="Board Game Concierge")

_SORTED_PILOT_GAMES = sorted(PILOT_GAMES_BY_BGG_ID.values(), key=lambda g: g["name"].casefold())

PILOT_GAME_NAMES = "\n".join(f"- {g['name']}" for g in _SORTED_PILOT_GAMES)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _extract_direct_game_name(text: str) -> str:
    matches = find_direct_game_mentions(text)
    if matches:
        return matches[0]["name"]
    return ""


def _is_short_reference(text: str) -> bool:
    return len(text.split()) <= 8


_TIPS_PREFIX_RE = re.compile(
    r"^(?:"
    r"(?:suggest|share|provide|show)\s+(?:some\s+)?(?:tips?|strategies?)\s+(?:for|on|about)\s+"
    r"|(?:give\s+(?:me\s+)?)?(?:some\s+)?(?:tips?|strategies?)\s+(?:for|on|about)\s+"
    r"|(?:tips?|strategies?)\s+(?:for|on|about)\s+"
    r"|(?:how\s+to\s+win|how\s+to\s+play|win\s+at)\s+"
    r"|(?:winning|play\s+better\s+at)\s+"
    r")",
    re.IGNORECASE,
)
_TIPS_SUFFIX_RE = re.compile(r"\b(?:tips?|strategy|strategies|for\s+winning|to\s+win)\b.*$", re.IGNORECASE)


def _extract_tips_game(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    cleaned = re.sub(r"^/tips?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = _TIPS_PREFIX_RE.sub("", cleaned).strip(" .,:;!?")
    cleaned = _TIPS_SUFFIX_RE.sub("", cleaned).strip(" .,:;!?")
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE).strip()

    if not cleaned:
        return ""

    game_row = resolve_game(cleaned)
    if game_row and game_row.get("name"):
        return game_row["name"]

    return cleaned


_BGG_RATING_RE = re.compile(
    r"(?:bgg\s+(?:rating|ratings|ranking|rank|score)|(?:rating|ratings|ranking|rank|score))"
    r"\s*(?:as|of|at|is|>=|=>|:)?\s*(\d+(?:\.\d+)?)\s*"
    r"(?:\+|or\s+higher|or\s+more|and\s+up|and\s+above)?",
    re.IGNORECASE,
)
_BGG_RATING_PLUS_RE = re.compile(
    r"(?:\b|\s)(\d+(?:\.\d+)?)\s*(?:\+|or\s+higher|or\s+more|and\s+up|and\s+above)\b",
    re.IGNORECASE,
)
_PLAYTIME_RE = re.compile(
    r"(?:around|about|approximately|roughly|for|can\s+play\s+for|play\s+for|time\s+budget\s+of|playtime\s+of)?\s*"
    r"(\d{1,3})\s*(?:mins?|minutes?|hrs?|hours?)\b",
    re.IGNORECASE,
)
_LIGHT_COMPLEXITY_RE = re.compile(
    r"(without\s+using\s+(?:a\s+)?lot\s+of\s+brain|without\s+using\s+too\s+much\s+brain|"
    r"not\s+too\s+much\s+brain|not\s+using\s+too\s+much\s+brain|light|easy|simple|casual|family)",
    re.IGNORECASE,
)
_HEAVY_COMPLEXITY_RE = re.compile(
    r"(more\s+depth|heavier|heavy|deep|deeper|complex|brainy)",
    re.IGNORECASE,
)


def _extract_min_bgg_rating(text: str) -> float | None:
    cleaned = " ".join(text.split())
    for pattern in (_BGG_RATING_RE, _BGG_RATING_PLUS_RE):
        match = pattern.search(cleaned)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _extract_target_playtime(text: str) -> int | None:
    cleaned = " ".join(text.split())
    match = _PLAYTIME_RE.search(cleaned)
    if not match:
        return None

    try:
        value = int(match.group(1))
    except ValueError:
        return None

    unit_text = cleaned[match.end(1):].casefold().lstrip()
    if unit_text.startswith(("hr", "hour")):
        return value * 60
    return value


def _extract_complexity_preference(text: str) -> str | None:
    cleaned = " ".join(text.split())
    light = _LIGHT_COMPLEXITY_RE.search(cleaned)
    heavy = _HEAVY_COMPLEXITY_RE.search(cleaned)
    if light and not heavy:
        return "light"
    if heavy and not light:
        return "heavy"
    if light and heavy:
        return "light"
    return None


def _matches_playtime(candidate: dict, target_minutes: int) -> bool:
    min_time = candidate.get("min_time")
    max_time = candidate.get("max_time")
    if min_time is None or max_time is None:
        return True
    return min_time <= target_minutes <= max_time


def _matches_complexity(candidate: dict, complexity_preference: str) -> bool:
    weight = candidate.get("weight")
    if weight is None:
        return True
    if complexity_preference == "light":
        return weight < 2.5
    if complexity_preference == "heavy":
        return weight >= 3.5
    return True


def _filter_recommendation_candidates(
    candidates: list[dict],
    target_minutes: int | None,
    complexity_preference: str | None,
) -> list[dict]:
    filtered = candidates

    if target_minutes is not None:
        time_matches = [c for c in filtered if _matches_playtime(c, target_minutes)]
        if not time_matches:
            return []
        filtered = time_matches

    if complexity_preference is not None:
        complexity_matches = [
            c for c in filtered if _matches_complexity(c, complexity_preference)
        ]
        if not complexity_matches:
            return []
        filtered = complexity_matches

    return filtered


def _reply(text: str) -> ConciergeResponse:
    return ConciergeResponse(reply=to_plain_text(text))


class ReportRequest(BaseModel):
    chat_id: str
    message: str


class AskRequest(BaseModel):
    chat_id: str
    question: str


class TipsRequest(BaseModel):
    chat_id: str
    game: str = ""


class RecommendRequest(BaseModel):
    chat_id: str
    preferences: str


class ResetRequest(BaseModel):
    chat_id: str


class ConciergeResponse(BaseModel):
    reply: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/games", response_model=ConciergeResponse)
def games() -> ConciergeResponse:
    lines = "\n".join(f"- {g['name']}" for g in _SORTED_PILOT_GAMES)
    return _reply(
        "Here's what's currently in my library:\n\n"
        f"{lines}\n\n"
        "Tell me what you're playing and I'll pull up the rules!"
    )


@app.get("/greeting", response_model=ConciergeResponse)
def greet() -> ConciergeResponse:
    return _reply(greeting())


@app.post("/reset", response_model=ConciergeResponse)
def reset(request: ResetRequest) -> ConciergeResponse:
    """Clears this chat's session game and any pending clarification - the
    conversation/preference state this backend owns. Deleting the bot's own
    recent Telegram messages is a separate concern handled entirely in the
    n8n workflow (message IDs live in n8n's static data, not here - this
    endpoint has no visibility into them)."""
    clear_session(request.chat_id)
    clear_pending(request.chat_id)
    return _reply(pick_variant("reset"))


def _ask_reply(game_slug: str, game_name: str, question: str) -> ConciergeResponse:
    """Shared by /ask and /report's pending-ask continuation below - both
    need the same "answer this question, now that we know the game" logic."""
    chunks = retrieve_followup_chunks(game_slug, question)
    reply = build_followup_answer(game_name, chunks, question)
    return _reply(reply)


def _tips_reply(game_slug: str, game_name: str) -> ConciergeResponse:
    """Shared by /tips and /report's pending-tips continuation below."""
    try:
        tip_snippet = get_tip(game_slug, game_name)
    except TipServiceUnavailable:
        return _reply(pick_variant("tips_service_unavailable", game_name=game_name))
    if tip_snippet is None:
        return _reply(pick_variant("no_tips", game_name=game_name))
    reply = build_tip(game_name, tip_snippet)
    return _reply(reply)


def _clarify_game_reference(current_game_name: str, referenced_game_name: str) -> ConciergeResponse:
    return _reply(
        pick_variant(
            "ambiguous_game_reference",
            current_game=current_game_name,
            referenced_game=referenced_game_name,
        )
    )


@app.post("/report", response_model=ConciergeResponse)
def report(request: ReportRequest) -> ConciergeResponse:
    # The n8n workflow routes any plain-text message with no recognized
    # slash command here as a default "what are we playing" catch-all. If
    # this chat's real request was blocked on "which game" (recommend needed
    # a player count that didn't come with an established game; ask/tips had
    # no session yet), this free text is completing THAT request, not
    # announcing a game for its own sake - finish the original request
    # instead of falling through to a generic report that ignores it.
    pending = get_pending(request.chat_id)
    if pending and pending["intent"] == "recommend":
        return _recommend_reply(request.chat_id, request.message)

    session = get_session_game(request.chat_id)
    if session is not None:
        game_row = resolve_game(request.message)
        game = PILOT_GAMES_BY_BGG_ID.get(game_row["id"]) if game_row else None
        if game and _game_reference_conflict(request.message, session["game_name"], game["name"]):
            return _clarify_game_reference(session["game_name"], game["name"])

    if pending and pending["intent"] in ("ask", "tips"):
        game_row = resolve_game(request.message)
        game = PILOT_GAMES_BY_BGG_ID.get(game_row["id"]) if game_row else None
        if game is None:
            # Still don't know the game - stay pending, let them try again.
            return _reply(pick_variant("unknown_game", game_names=PILOT_GAME_NAMES))

        remember_report(request.chat_id, game["slug"], game["name"])
        clear_pending(request.chat_id)
        if pending["intent"] == "ask":
            return _ask_reply(game["slug"], game["name"], pending["question"])
        return _tips_reply(game["slug"], game["name"])

    game_row = resolve_game(request.message)
    game = PILOT_GAMES_BY_BGG_ID.get(game_row["id"]) if game_row else None

    if game is None:
        return _reply(pick_variant("unknown_game", game_names=PILOT_GAME_NAMES))

    chunks = retrieve_digest_chunks(game["slug"])
    if not chunks:
        # Retrieval came up empty (or every candidate chunk was too low-
        # confidence to keep, see RAG_MIN_SCORE) - say so plainly rather than
        # asking the LLM to write a digest ungrounded in anything real.
        return _reply(pick_variant("no_rulebook_coverage", game_name=game["name"]))

    reply = build_report(game["name"], chunks)
    remember_report(request.chat_id, game["slug"], game["name"])
    return _reply(reply)


@app.post("/ask", response_model=ConciergeResponse)
def ask(request: AskRequest) -> ConciergeResponse:
    session = get_session_game(request.chat_id)
    if session is None:
        remember_pending(request.chat_id, "ask", question=request.question)
        return _reply(pick_variant("no_session"))

    referenced_game_name = _extract_direct_game_name(request.question)
    if (
        referenced_game_name
        and _slugify(referenced_game_name) != session["game_slug"]
        and _is_short_reference(request.question)
    ):
        return _clarify_game_reference(session["game_name"], referenced_game_name)

    return _ask_reply(session["game_slug"], session["game_name"], request.question)


@app.post("/tips", response_model=ConciergeResponse)
def tips(request: TipsRequest) -> ConciergeResponse:
    session = get_session_game(request.chat_id)
    if request.game.strip():
        referenced_game_name = _extract_direct_game_name(request.game)
        if session:
            if (
                referenced_game_name
                and _slugify(referenced_game_name) != session["game_slug"]
                and _is_short_reference(request.game)
            ):
                return _clarify_game_reference(session["game_name"], referenced_game_name)
            return _tips_reply(session["game_slug"], session["game_name"])

        if referenced_game_name:
            game_slug = _slugify(referenced_game_name)
            return _tips_reply(game_slug, referenced_game_name)

        return _reply(pick_variant("missing_tips_game"))

    if session is None:
        remember_pending(request.chat_id, "tips")
        return _reply(pick_variant("no_session"))

    return _tips_reply(session["game_slug"], session["game_name"])


def _recommend_reply(chat_id: str, preferences: str) -> ConciergeResponse:
    """Shared by /recommend and /report's pending-recommend continuation
    (see report() above) - both ultimately need the same "do we have a
    workable player count yet" logic, just fed from different endpoints."""
    player_count = extract_player_count(preferences)
    min_bgg_rating = _extract_min_bgg_rating(preferences)
    target_playtime = _extract_target_playtime(preferences)
    complexity_preference = _extract_complexity_preference(preferences)
    if player_count is not None and player_count <= 0:
        player_count = None  # e.g. "0 players" - treat as no real count given

    if player_count is None:
        remember_pending(chat_id, "recommend")
        return _reply(pick_variant("missing_player_count"))

    candidates = find_candidates_with_rating(player_count, min_bgg_rating)
    candidates = _filter_recommendation_candidates(
        candidates,
        target_playtime,
        complexity_preference,
    )
    if not candidates:
        # Still waiting on a workable count, so stay pending rather than
        # clearing - the next free-text reply should keep coming back here.
        remember_pending(chat_id, "recommend")
        constraint_bits = [f"{player_count} players"]
        if min_bgg_rating is not None:
            constraint_bits.append(f"BGG {str(min_bgg_rating).rstrip('0').rstrip('.')}+")
        if target_playtime is not None:
            constraint_bits.append(f"around {target_playtime} min")
        if complexity_preference is not None:
            constraint_bits.append(f"{complexity_preference} complexity")
        if len(constraint_bits) == 1:
            constraint_text = constraint_bits[0]
        elif len(constraint_bits) == 2:
            constraint_text = " and ".join(constraint_bits)
        else:
            constraint_text = ", ".join(constraint_bits[:-1]) + f", and {constraint_bits[-1]}"
        return _reply(
            f"I couldn't find any games in my catalog that match {constraint_text}. "
            "Want to relax one of the filters?"
        )

    clear_pending(chat_id)
    reply = build_recommendation(preferences, player_count, candidates)
    return _reply(reply)


@app.post("/recommend", response_model=ConciergeResponse)
def recommend(request: RecommendRequest) -> ConciergeResponse:
    return _recommend_reply(request.chat_id, request.preferences)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
