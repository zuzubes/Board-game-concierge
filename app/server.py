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
from app.clients.game_lookup import resolve_game
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
    r"(?:bgg\s+rating|rating)\s*(\d+(?:\.\d+)?)\s*(?:\+|or\s+higher|or\s+more|and\s+up|and\s+above)?",
    re.IGNORECASE,
)
_BGG_RATING_PLUS_RE = re.compile(
    r"(?:\b|\s)(\d+(?:\.\d+)?)\s*(?:\+|or\s+higher|or\s+more|and\s+up|and\s+above)\b",
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

    return _ask_reply(session["game_slug"], session["game_name"], request.question)


@app.post("/tips", response_model=ConciergeResponse)
def tips(request: TipsRequest) -> ConciergeResponse:
    if request.game.strip():
        game_name = _extract_tips_game(request.game)
        if not game_name:
            return _reply(pick_variant("missing_tips_game"))
        game_slug = _slugify(game_name)
        return _tips_reply(game_slug, game_name)

    session = get_session_game(request.chat_id)
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
    if player_count is not None and player_count <= 0:
        player_count = None  # e.g. "0 players" - treat as no real count given

    if player_count is None:
        remember_pending(chat_id, "recommend")
        return _reply(pick_variant("missing_player_count"))

    candidates = find_candidates_with_rating(player_count, min_bgg_rating)
    if not candidates:
        # Still waiting on a workable count, so stay pending rather than
        # clearing - the next free-text reply should keep coming back here.
        remember_pending(chat_id, "recommend")
        if min_bgg_rating is not None:
            return _reply(
                pick_variant(
                    "no_candidates_with_rating",
                    player_count=str(player_count),
                    min_bgg_rating=str(min_bgg_rating).rstrip("0").rstrip("."),
                )
            )
        return _reply(pick_variant("no_candidates", player_count=str(player_count)))

    clear_pending(chat_id)
    reply = build_recommendation(preferences, player_count, candidates)
    return _reply(reply)


@app.post("/recommend", response_model=ConciergeResponse)
def recommend(request: RecommendRequest) -> ConciergeResponse:
    return _recommend_reply(request.chat_id, request.preferences)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
