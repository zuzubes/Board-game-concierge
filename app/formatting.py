"""Plain-text cleanup helpers for Telegram replies."""

from __future__ import annotations

import re

_HTML_TAG_RE = re.compile(r"</?(?:b|i|u|s|tg-spoiler|code)>", re.IGNORECASE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<!\w)\*(.+?)\*(?!\w)", re.DOTALL)
_UNDERLINE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_CODE_RE = re.compile(r"`([^`\n]+)`")
_PAGE_REF_RE = re.compile(r"\s*\(?\b(?:p\.|page)\s*\d+\)?", re.IGNORECASE)


def _normalize_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        bare = stripped.removeprefix("||").removesuffix("||").strip()
        if "Strategy Tip:" in bare and not bare.startswith("💡"):
            line = line.replace("Strategy Tip:", "💡 Strategy Tip:", 1)
        elif "Tip:" in bare and not bare.startswith("💡"):
            line = line.replace("Tip:", "💡 Tip:", 1)
        elif "Plays like:" in bare and not bare.startswith("🤝"):
            line = line.replace("Plays like:", "🤝 Plays like:", 1)
        lines.append(line)
    return "\n".join(lines)


def to_plain_text(text: str) -> str:
    text = _normalize_lines(text)
    text = _PAGE_REF_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    text = text.replace("||", "")
    text = _CODE_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(r"\1", text)
    text = _UNDERLINE_RE.sub(r"\1", text)
    text = _STRIKE_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = text.replace("*", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
