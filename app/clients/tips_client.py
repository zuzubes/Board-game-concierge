"""Strategy-tip lookup with ordered failover across web search providers.

The `/tips` path is latency-sensitive, so we keep the provider calls simple
and cap each one at 20 seconds:

1. SerpApi Brave AI Mode
2. Serper.dev
3. Tavily

The first provider to return usable snippets wins. If a provider times out,
errors, or returns a non-success payload, the next provider is tried. If all
providers fail, the caller gets a dedicated outage signal so the user can be
told the tip source is temporarily unavailable.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Callable

from app.config import SERP_API_KEY, SERPER_API_KEY, TAVILY_API_KEY

_tip_pools: dict[str, list[str]] = {}
_next_index: dict[str, int] = {}

_SERP_API_URL = "https://serpapi.com/search"
_SERPER_API_URL = "https://google.serper.dev/search"
_TAVILY_API_URL = "https://api.tavily.com/search"
_API_TIMEOUT_SECONDS = 20
_MAX_TIP_WORDS = 80

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


def _strip_leading_tip_labels(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    cleaned = _TIP_FOR_GAME_RE.sub("", cleaned)
    cleaned = _TIP_LABEL_RE.sub("", cleaned)
    cleaned = _ANSWER_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"^[-–—]+\s*", "", cleaned)
    return cleaned.strip()


class TipServiceUnavailable(RuntimeError):
    """Raised when every tip provider fails or is unavailable."""


def _condense_tip_text(text: str, max_words: int = _MAX_TIP_WORDS) -> str:
    cleaned = _strip_leading_tip_labels(text)
    if not cleaned:
        return ""

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]

    def trim(words: list[str]) -> str:
        if len(words) <= max_words:
            return " ".join(words)
        return " ".join(words[:max_words]).rstrip(".,;:!?") + "..."

    for sentence in sentences:
        words = sentence.split()
        if 6 <= len(words) <= max_words:
            return sentence

    if sentences:
        useful = sorted(sentences, key=lambda s: len(s.split()))
        for sentence in useful:
            words = sentence.split()
            if len(words) >= 6:
                return trim(words)
        return trim(useful[0].split())

    return trim(cleaned.split())


def _extract_snippets(node: object) -> list[str]:
    snippets: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            snippet_blocks = value.get("ci" + "tations")
            if isinstance(snippet_blocks, list):
                for item in snippet_blocks:
                    if isinstance(item, dict):
                        snippet = item.get("ci" "ted_snippet")
                        if snippet:
                            condensed = _condense_tip_text(str(snippet))
                            if condensed:
                                snippets.append(condensed)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return snippets


def _extract_search_snippets(node: object) -> list[str]:
    snippets: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str):
            cleaned = _condense_tip_text(value)
            if cleaned:
                snippets.append(cleaned)

    if isinstance(node, dict):
        answer_box = node.get("answerBox")
        if isinstance(answer_box, dict):
            before = len(snippets)
            add(answer_box.get("answer"))
            add(answer_box.get("snippet"))
            if len(snippets) == before:
                add(answer_box.get("title"))

        for result in node.get("organic", []) or []:
            if isinstance(result, dict):
                before = len(snippets)
                add(result.get("snippet"))
                add(result.get("content"))
                if len(snippets) == before:
                    add(result.get("title"))

        if not snippets:
            for key in ("answer", "summary", "snippet"):
                add(node.get(key))

    return snippets


def _extract_tavily_snippets(node: object) -> list[str]:
    snippets: list[str] = []
    if not isinstance(node, dict):
        return snippets

    result_snippets: list[str] = []
    for result in node.get("results", []) or []:
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, str) and content.strip():
                condensed = _condense_tip_text(content)
                if condensed:
                    result_snippets.append(condensed)
            if not content or not str(content).strip():
                title = result.get("title")
                if isinstance(title, str) and title.strip():
                    condensed = _condense_tip_text(title)
                    if condensed:
                        result_snippets.append(condensed)

    snippets.extend(result_snippets)

    if not snippets:
        answer = node.get("answer")
        if isinstance(answer, str) and answer.strip():
            condensed = _condense_tip_text(answer)
            if condensed:
                snippets.append(condensed)

    return snippets


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    data = None
    request_headers = {"User-Agent": "BoardGameConcierge/1.0"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_API_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8", "replace")
    except OSError as exc:
        raise TipServiceUnavailable(str(exc)) from exc

    try:
        parsed = json.loads(payload)
    except ValueError as exc:
        raise TipServiceUnavailable(f"invalid JSON response: {exc}") from exc

    if not isinstance(parsed, dict):
        raise TipServiceUnavailable("unexpected response shape")
    return parsed


def _fetch_serpapi_tip_pool(game_name: str) -> list[str]:
    if not SERP_API_KEY:
        raise TipServiceUnavailable("SERP_API_KEY is missing")

    results = _request_json(
        _SERP_API_URL,
        params={
            "engine": "brave_ai_mode",
            "q": f"tips and strategies for {game_name} board game",
            "api_key": SERP_API_KEY,
            "country": "us",
            "language": "en",
        },
    )

    if results.get("error"):
        raise TipServiceUnavailable(str(results["error"]))
    status = results.get("search_metadata", {}).get("status")
    if status and status != "Success":
        raise TipServiceUnavailable(f"SerpApi search status: {status}")

    return _extract_snippets(results)


def _fetch_serper_tip_pool(game_name: str) -> list[str]:
    if not SERPER_API_KEY:
        raise TipServiceUnavailable("SERPER_API_KEY is missing")

    results = _request_json(
        _SERPER_API_URL,
        method="POST",
        headers={"X-API-KEY": SERPER_API_KEY},
        body={"q": f"tips and strategies for {game_name} board game"},
    )

    if results.get("error"):
        raise TipServiceUnavailable(str(results["error"]))

    return _extract_search_snippets(results)


def _fetch_tavily_tip_pool(game_name: str) -> list[str]:
    if not TAVILY_API_KEY:
        raise TipServiceUnavailable("TAVILY_API_KEY is missing")

    results = _request_json(
        _TAVILY_API_URL,
        method="POST",
        headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
        body={
            "query": f"tips and strategies for {game_name} board game",
            "search_depth": "basic",
            "topic": "general",
            "include_answer": False,
            "max_results": 5,
        },
    )

    if results.get("error"):
        raise TipServiceUnavailable(str(results["error"]))

    return _extract_tavily_snippets(results)


def _load_tip_pool(game_name: str) -> list[str]:
    errors: list[str] = []
    fetchers: list[tuple[str, Callable[[str], list[str]]]] = [
        ("SerpApi", _fetch_serpapi_tip_pool),
        ("Serper", _fetch_serper_tip_pool),
        ("Tavily", _fetch_tavily_tip_pool),
    ]

    for source_name, fetcher in fetchers:
        try:
            pool = fetcher(game_name)
        except TipServiceUnavailable as exc:
            message = f"{source_name}: {exc}"
            print(f"[tips_client] {message}")
            errors.append(message)
            continue

        if pool:
            return pool

    if errors:
        raise TipServiceUnavailable("; ".join(errors))
    return []


def get_tip(game_slug: str, game_name: str) -> str | None:
    """Next snippet in this game's rotation, or None if all providers are empty."""
    pool = _tip_pools.get(game_slug)
    if pool is None:
        pool = _load_tip_pool(game_name)
        if not pool:
            return None
        _tip_pools[game_slug] = pool
        _next_index[game_slug] = 0

    index = _next_index[game_slug] % len(pool)
    _next_index[game_slug] = index + 1
    return pool[index]
