"""Variant phrasing pools for the concierge's canned (non-LLM) responses.

These are the fixed edge-case replies - greeting, "I don't know this game,"
"tell me who's playing first" - that get hit repeatedly across a session.
Picking randomly from a few options keeps them from feeling like the same
templated string every time. Kept centralized here (not duplicated into the
n8n workflow as static text) so there's exactly one place to edit wording.

Only the framing sentences vary - reference content a user actually needs
verbatim (the command list, game names) stays fixed across variants so
variety never comes at the cost of information.
"""

from __future__ import annotations

import random

_GREETING_OPENERS = [
    "Hey there, welcome to the table! 🎲",
    "Well hello! 🎲 Glad you pulled up a chair.",
    "Hey! 🎲 Ready to sort out game night?",
]

_GREETING_BODY = """\
I'm your Board Game Concierge — think of me as that friend who's played \
everything and can't wait to help you find the right game, learn one you \
already own, or get your group sorted for game night.

Here's how to put me to work:

`/recommend` — tell me your group size, vibe, and time budget, and I'll \
give you a few confident picks (not a menu)
`/list` — see what rulebooks are in my library
`/help` — a refresher on a game you'd like to start with (e.g. /help \
Wingspan)
`/ask` — got a rules question? "How does scoring work in Wingspan?" — \
I'll answer straight, grounded in the actual rulebook
`/tips` — I can give you some top secrets to win the game. Hit me up!
`/reset` — start clean: forgets what we were talking about and clears my \
recent messages (last 48 hours)"""

_GREETING_CLOSERS = [
    "Tell me what you're playing tonight, or what you're in the mood for — I'll take it from there.",
    "So - what are we playing tonight?",
    "Let me know what's on the table tonight and we'll get you sorted.",
]

_UNKNOWN_GAME_VARIANTS = [
    "I don't have a rulebook loaded for that one yet - here's what I do "
    "know:\n\n{game_names}\n\nWant a digest for one of those instead?",
    "That one's not in my library yet - so far I've only got:\n\n"
    "{game_names}\n\nWant a rules refresher for one of those?",
    "I haven't got the rulebook for that game yet - I'm currently only "
    "stocked on:\n\n{game_names}\n\nHappy to walk you through one of those "
    "instead?",
]

_NO_RULEBOOK_COVERAGE_VARIANTS = [
    "I don't have the rulebook for that one yet, so I can't put together a "
    "reliable digest for {game_name} - don't want to guess at rules and get "
    "you in trouble at the table.",
    "I'm coming up empty on rulebook content for {game_name} - rather than "
    "make something up, I'll be straight with you: I can't give you a "
    "grounded digest for this one right now.",
    "I don't actually have solid rulebook coverage for {game_name} yet, so "
    "I'd rather admit that than hand you a guess dressed up as a rule.",
]

_NO_SESSION_VARIANTS = [
    "I don't have a game in mind for this chat yet - tell me what you're "
    'playing first (e.g. "we\'re playing Wingspan tonight") and I\'ll take '
    "it from there.",
    "I need to know what we're playing before I can answer that one - let "
    'me know the game (e.g. "we\'re playing Wingspan tonight") and fire '
    "away.",
    "Nothing queued up for this chat yet - tell me the game first and I'll "
    "take it from there.",
]

_NO_TIPS_VARIANTS = [
    "I couldn't dig up a solid tip for {game_name} right now - want to try "
    "again in a bit?",
    "Coming up empty on outside strategy tips for {game_name} at the "
    "moment - mind giving it another shot shortly?",
    "I'm not finding a good tip for {game_name} right now - try me again "
    "in a little while?",
]

_MISSING_TIPS_GAME_VARIANTS = [
    "Tell me which game you want tips for, and I'll take it from there.",
    "I can do that - just name the game first.",
    "Give me the game name, and I'll pull a tip for it.",
]

_TIPS_SERVICE_UNAVAILABLE_VARIANTS = [
    "I'm having trouble reaching my tip source for {game_name} right now, "
    "so I'm skipping strategy tips for the moment. Try again in a little "
    "while.",
    "The tip service for {game_name} is acting up on my side just now, so "
    "I can't pull a strategy tip yet. Give me another shot later.",
    "I can't reach the strategy-tip source for {game_name} right now, so "
    "I'm holding off instead of guessing. Try again soon.",
]

_MISSING_PLAYER_COUNT_VARIANTS = [
    "Happy to recommend something - how many players are you expecting "
    "tonight?",
    "I'd love to help - first, how many people are playing?",
    "Let's find you a game - how many players at the table tonight?",
]

_NO_CANDIDATES_VARIANTS = [
    "I couldn't find a good match for {player_count} players in my catalog "
    "right now - want to try a different player count?",
    "Nothing in my catalog quite fits {player_count} players - mind trying "
    "a different count?",
    "Coming up short for {player_count} players in what I've got - want to "
    "give me another number to work with?",
]

_NO_CANDIDATES_WITH_RATING_VARIANTS = [
    "I couldn't find any games in my catalog that match {player_count} players "
    "and a BGG rating of {min_bgg_rating}+ - want to relax one of those filters?",
    "Nothing in my catalog fits both {player_count} players and BGG {min_bgg_rating}+ "
    "right now - try a lower rating threshold or a different player count?",
    "I don't have any {player_count}-player games rated {min_bgg_rating}+ or above "
    "in my catalog - want to widen the search a bit?",
]

_RESET_VARIANTS = [
    "All cleared - I've forgotten what we were playing and any question "
    "that was in flight. For messages older than 48 hours, or anything "
    "sent by others in a group, use Telegram's own \"Clear History\" - "
    "that's the right tool for those, not me.",
    "Done - clean slate, no game or pending question on file for this "
    "chat anymore. For older messages, or ones from other people in a "
    "group, Telegram's built-in \"Clear History\" is the way to go.",
    "Reset complete - I'm starting fresh with you. Anything past 48 hours "
    "old, or sent by someone else in a group chat, is out of my reach - "
    "use Telegram's \"Clear History\" for those.",
]

_VARIANTS: dict[str, list[str]] = {
    "unknown_game": _UNKNOWN_GAME_VARIANTS,
    "no_rulebook_coverage": _NO_RULEBOOK_COVERAGE_VARIANTS,
    "no_session": _NO_SESSION_VARIANTS,
    "missing_player_count": _MISSING_PLAYER_COUNT_VARIANTS,
    "no_candidates": _NO_CANDIDATES_VARIANTS,
    "no_candidates_with_rating": _NO_CANDIDATES_WITH_RATING_VARIANTS,
    "no_tips": _NO_TIPS_VARIANTS,
    "missing_tips_game": _MISSING_TIPS_GAME_VARIANTS,
    "tips_service_unavailable": _TIPS_SERVICE_UNAVAILABLE_VARIANTS,
    "reset": _RESET_VARIANTS,
}


def pick_variant(key: str, **kwargs: str) -> str:
    template = random.choice(_VARIANTS[key])
    return template.format(**kwargs) if kwargs else template


def greeting() -> str:
    opener = random.choice(_GREETING_OPENERS)
    closer = random.choice(_GREETING_CLOSERS)
    return f"{opener}\n\n{_GREETING_BODY}\n\n{closer}"
