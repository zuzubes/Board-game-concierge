"""LangChain synthesis: persona system prompt + retrieved rulebook chunks ->
a short, on-persona Telegram message.

v1 is a single prompt template + one LLM call per report/answer - see
project plan's Technology Selection Framework: a simple chain is enough
until v2 needs query classification/routing.
"""

from __future__ import annotations

import re
from functools import lru_cache

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from app.config import CHAT_MODEL
from app.persona import PERSONA_SYSTEM_PROMPT

_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=CHAT_MODEL, temperature=0.3, timeout=20, max_retries=1)
    return _llm


_HEADING_RE = re.compile(r"^#{1,6}\s*(.+)$", re.MULTILINE)
_AUTOMATION_LINE_RE = re.compile(
    r"^.*\b(sent|generated|created)\s+automatically\b.*$\n?",
    re.MULTILINE | re.IGNORECASE,
)
_TIP_LABEL_RE = re.compile(
    r"^(?:"
    r"tip(?:s)?"
    r"|strategy(?:\s+tip)?"
    r"|hint(?:s)?"
    r"|advice"
    r")\s*:\s*",
    re.IGNORECASE,
)
_TIP_FOR_GAME_RE = re.compile(r"^tip\s+for\s+[^:]+:\s*", re.IGNORECASE)
_ANSWER_PREFIX_RE = re.compile(r"^(?:answer|response|result)\s*:\s*", re.IGNORECASE)


def _sanitize_reply(text: str) -> str:
    """Belt-and-suspenders cleanup on top of the persona's formatting rules -
    the LLM doesn't always follow instructions perfectly, and Telegram's
    formatting parser renders a stray '#' as a literal character rather than
    silently ignoring it, so strip/convert anything that would leak through.
    """
    text = _HEADING_RE.sub(lambda m: m.group(1).strip(), text)
    text = _AUTOMATION_LINE_RE.sub("", text)
    return text.strip()


def _strip_tip_prefixes(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    cleaned = _TIP_FOR_GAME_RE.sub("", cleaned)
    cleaned = _TIP_LABEL_RE.sub("", cleaned)
    cleaned = _ANSWER_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"^[-–—]+\s*", "", cleaned)
    return cleaned.strip()


def _format_chunks(chunks: list[dict]) -> str:
    if not chunks:
        return "(no rulebook excerpts retrieved)"
    return "\n\n".join(c["text"] for c in chunks)


def _chunk_signature(chunks: list[dict]) -> tuple[tuple[object, str], ...]:
    return tuple((chunk.get("page"), chunk.get("text", "")) for chunk in chunks)


def _candidate_signature(candidates: list[dict]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            candidate.get("bgg_id"),
            candidate.get("name"),
            candidate.get("min_players"),
            candidate.get("max_players"),
            candidate.get("weight"),
            candidate.get("age"),
            candidate.get("bayes_rating"),
            candidate.get("min_time"),
            candidate.get("max_time"),
            tuple(candidate.get("mechanics") or ()),
            tuple(candidate.get("categories") or ()),
            candidate.get("description", "")[:200],
        )
        for candidate in candidates
    )


@lru_cache(maxsize=64)
def _build_report_cached(game_name: str, chunk_sig: tuple[tuple[object, str], ...]) -> str:
    user_prompt = f"""\
Generate tonight's pre-session report for {game_name}.

Retrieved rulebook excerpts:
{_format_chunks([{"page": page, "text": text} for page, text in chunk_sig])}

Write the report as:
1. One warm, energetic opening line naming the game (e.g. "Let's get you set
   up with an exciting game of {game_name}!"), with a fitting emoji - this is
   the very first thing the player sees, make it feel like the concierge
   greeting them, not a document title. Keep it plain text.
2. 5-10 short rule steps (setup, turn structure, scoring/win condition), each
   one sentence. Only use what's in the retrieved excerpts above - if
   something isn't covered, leave it out rather than guessing.
   Do not mention page numbers or other provenance markers in the final text.
3. Add one blank line.
4. Add a concise strategy tip line, then a separate "plays like X" line with
   a 🤝 emoji. Keep both lines plain text.
5. End with: "Enjoy your game and don't forget to `/ask` if you have
   questions or `/tips` if you really want to win 🏆"

Keep the whole message short enough to read once at the table, in your
concierge voice - fun, warm, a couple of well-placed emoji, never a wall of
plain text."""

    messages = [SystemMessage(content=PERSONA_SYSTEM_PROMPT), ("human", user_prompt)]
    return _sanitize_reply(_get_llm().invoke(messages).content)


def build_report(game_name: str, chunks: list[dict]) -> str:
    return _build_report_cached(game_name, _chunk_signature(chunks))


def _weight_label(weight: float | None) -> str:
    """Light/medium/heavy label computed in Python, not left to the LLM -
    deriving a category from a number is exactly the kind of arithmetic-
    adjacent step models get wrong under real testing (confirmed: it
    mislabeled a 3.0-weight game as "light" and a 2.4-weight game as
    "medium" when asked to derive this itself)."""
    if weight is None:
        return "not rated"
    if weight < 2.5:
        return "light"
    if weight <= 3.5:
        return "medium"
    return "heavy"


def _format_candidates(candidates: list[dict]) -> str:
    if not candidates:
        return "(no candidate games available)"
    lines = []
    for c in candidates:
        weight = f"{_weight_label(c['weight'])} ({c['weight']:.1f}/5)" if c["weight"] else "not rated"
        age = f"{c['age']}+" if c["age"] is not None else "not listed"
        rating = f"{c['bayes_rating']:.2f}/10" if c["bayes_rating"] is not None else "not rated"
        if c["min_time"] and c["max_time"]:
            playtime = f"{c['min_time']}-{c['max_time']} min"
        elif c["max_time"]:
            playtime = f"~{c['max_time']} min"
        else:
            playtime = "not listed"
        tags = ", ".join(c["mechanics"] + c["categories"]) or "uncategorized"
        snippet = (c["description"] or "")[:200]
        lines.append(
            f"- {c['name']} (BGG ID {c['bgg_id']}): {c['min_players']}-{c['max_players']} "
            f"players, complexity {weight}, min age {age}, BGG rating {rating}, "
            f"playtime {playtime}, tags: {tags}\n"
            f"  keywords (lemmatized, not prose): {snippet}"
        )
    return "\n".join(lines)


def build_recommendation(preferences: str, player_count: int, candidates: list[dict]) -> str:
    normalized_preferences = " ".join(preferences.split())
    return _build_recommendation_cached(
        normalized_preferences, player_count, _candidate_signature(candidates)
    )


@lru_cache(maxsize=128)
def _build_recommendation_cached(
    preferences: str, player_count: int, candidate_sig: tuple[tuple[object, ...], ...]
) -> str:
    user_prompt = f"""\
A player wants a game recommendation for {player_count} player(s). In their \
own words: "{preferences}"

Candidate games (the ONLY games you may recommend - never suggest a game \
that isn't in this list, and never invent details not shown here):
{_format_candidates([{
    "bgg_id": bgg_id,
    "name": name,
    "min_players": min_players,
    "max_players": max_players,
    "weight": weight,
    "age": age,
    "bayes_rating": bayes_rating,
    "min_time": min_time,
    "max_time": max_time,
    "mechanics": list(mechanics),
    "categories": list(categories),
    "description": description,
} for (
    bgg_id,
    name,
    min_players,
    max_players,
    weight,
    age,
    bayes_rating,
    min_time,
    max_time,
    mechanics,
    categories,
    description,
) in candidate_sig])}

Pick from the candidate list above:
1. ONE confident primary pick - the single best fit for the stated
   preferences, not just the highest-rated candidate. If they said "light"
   or "quick," don't pick a medium/heavy game and call it light in your
   description - actually pick a lighter one. With a one-line reason it fits.
2. TWO alternatives, each framed by direction relative to the primary pick
   (e.g. "if you want something lighter" or "if you want more depth" or "if
   you have less time") - not just second-best guesses, genuine contrasts.
   Before you write each direction phrase, check it against the actual
   complexity/playtime numbers of the picks - only say "lighter" if the
   alternative's complexity label/number is genuinely lower than the primary
   pick's, only say "more depth"/"heavier" if it's genuinely higher, only say
   "less time" if its playtime is genuinely shorter. If nothing about an
   alternative is a clean contrast on any axis, pick a different phrase that
   is actually true (e.g. "if you want a different theme") rather than
   forcing one of the above.

For each of the 3 picks, include:
- The game name
- Player range (min-max players)
- Playtime range
- Complexity, if available - use the light/medium/heavy label exactly as
  given for that game above, don't recompute it yourself. Omit this line
  entirely if complexity is "not rated" above.
- Minimum age
- BGG rating

Write it in your concierge voice - a short warm intro sentence, then the 3
picks, then one natural next step (e.g. offering a rules digest for
whichever one they pick)."""

    messages = [SystemMessage(content=PERSONA_SYSTEM_PROMPT), ("human", user_prompt)]
    return _sanitize_reply(_get_llm().invoke(messages).content)


def build_followup_answer(game_name: str, chunks: list[dict], question: str) -> str:
    normalized_question = " ".join(question.split())
    return _build_followup_answer_cached(game_name, normalized_question, _chunk_signature(chunks))


@lru_cache(maxsize=128)
def _build_followup_answer_cached(
    game_name: str, question: str, chunk_sig: tuple[tuple[object, str], ...]
) -> str:
    if not chunk_sig:
        user_prompt = f"""\
A player asked this follow-up question about {game_name}: "{question}"

No matching rulebook excerpts were retrieved for this question. Tell them
plainly and warmly that you can't find this in the rulebook you have for
this game, and suggest checking the physical rulebook or an official FAQ."""
    else:
        user_prompt = f"""\
A player asked this follow-up question about {game_name}: "{question}"

Retrieved rulebook excerpts:
{_format_chunks([{"page": page, "text": text} for page, text in chunk_sig])}

Answer the question directly using only these excerpts. If the excerpts
don't actually answer the question, say so plainly instead of guessing.
Keep it short - a few sentences."""

    messages = [SystemMessage(content=PERSONA_SYSTEM_PROMPT), ("human", user_prompt)]
    return _sanitize_reply(_get_llm().invoke(messages).content)


def build_tip(game_name: str, tip_snippet: str) -> str:
    # `/tips` is the most latency-sensitive path in the bot. Instead of
    # making a second LLM round-trip here, turn the cited snippet into a short
    # tip locally so the response stays fast and predictable.
    text = _strip_tip_prefixes(tip_snippet)
    if not text:
        return f"Tip for {game_name}: Play to your position on the board, not just your next move."

    # Prefer an actual strategy sentence, not provider boilerplate.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    boilerplate_re = re.compile(
        r"\b(written|articles?|below|would love to help|next steps?|over 10,?000 words|series of articles)\b",
        re.IGNORECASE,
    )
    strategy_re = re.compile(
        r"\b(control|attack|defend|focus|concentrat|expand|position|hold|pressure|build|keep|block|score|tempo|timing|risk)\b",
        re.IGNORECASE,
    )

    scored = [
        (2 if strategy_re.search(sentence) else 0, -len(sentence.split()), sentence)
        for sentence in sentences
        if not boilerplate_re.search(sentence)
    ]
    if scored:
        scored.sort(reverse=True)
        tip = scored[0][2]
    else:
        tip = next((s for s in sentences if len(s) >= 20), sentences[0] if sentences else text)
    tip = tip.strip('"“”')
    words = tip.split()
    if len(words) > 50:
        tip = " ".join(words[:50]).rstrip(".,;:!?") + "..."
    elif len(tip) > 220:
        tip = tip[:217].rstrip() + "..."
    if tip and tip[-1] not in ".!?":
        tip += "."
    return f"Tip for {game_name}: {tip}"
