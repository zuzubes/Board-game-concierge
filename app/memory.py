"""Short per-Telegram-chat memory so a follow-up question resolves against
the game from the original digest request. Deliberately simple - v1 scope is
one grounded follow-up per session, not full multi-turn planning (see
project plan's "Conversation memory (v1, basic)").

Also tracks a "pending intent" per chat - set whenever the bot's real answer
is blocked on missing info (recommend's "how many players?", or ask/tips
needing a game established first), so the next plain-text message (which the
n8n workflow otherwise routes to /report as a default "what are we playing"
catch-all) gets recognized as completing that original request instead of
being misread as a fresh, unrelated game announcement. Carries whatever
payload the original request needs to finish once unblocked - e.g. ask's
question text, so answering "which game" doesn't lose what was actually
asked.
"""

from __future__ import annotations

_sessions: dict[str, dict] = {}
_pending: dict[str, dict] = {}


def remember_report(chat_id: str, game_slug: str, game_name: str) -> None:
    _sessions[chat_id] = {"game_slug": game_slug, "game_name": game_name}


def get_session_game(chat_id: str) -> dict | None:
    return _sessions.get(chat_id)


def clear_session(chat_id: str) -> None:
    _sessions.pop(chat_id, None)


def remember_pending(chat_id: str, intent: str, **payload: str) -> None:
    _pending[chat_id] = {"intent": intent, **payload}


def get_pending(chat_id: str) -> dict | None:
    return _pending.get(chat_id)


def clear_pending(chat_id: str) -> None:
    _pending.pop(chat_id, None)
