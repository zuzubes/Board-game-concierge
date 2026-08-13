"""Pinecone retrieval for rulebook chunks, filtered to one game at a time."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from app.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, PINECONE_INDEX_NAME, RAG_MIN_SCORE

_vectorstore: PineconeVectorStore | None = None
_digest_cache: dict[tuple[str, int], list[dict]] = {}
_followup_cache: dict[tuple[str, str, int], list[dict]] = {}

# Fixed queries that together cover what a "how do I play this" digest needs.
# /report isn't answering one specific question, so it retrieves against all
# three instead of a single query.
DIGEST_QUERIES = [
    "game setup and how to start playing",
    "how a turn works, what actions a player can take",
    "how the game ends, scoring, and winning",
]


def get_vectorstore() -> PineconeVectorStore:
    global _vectorstore
    if _vectorstore is None:
        embeddings = OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            dimensions=EMBEDDING_DIMENSIONS,
            timeout=15,
            max_retries=1,
        )
        _vectorstore = PineconeVectorStore(index_name=PINECONE_INDEX_NAME, embedding=embeddings)
    return _vectorstore


def retrieve_chunks_for_game(game_slug: str, query: str, k: int = 4) -> list[dict]:
    """Chunks scored below RAG_MIN_SCORE are dropped here, at the source, so
    every caller (digest + follow-up) automatically treats a low-confidence
    match as no match rather than silently using it as grounding."""
    results = get_vectorstore().similarity_search_with_score(
        query, k=k, filter={"game_slug": game_slug}
    )
    return [
        {"text": doc.page_content, "page": doc.metadata.get("page"), "score": score}
        for doc, score in results
        if score >= RAG_MIN_SCORE
    ]


def retrieve_digest_chunks(game_slug: str, per_query_k: int = 3) -> list[dict]:
    """Deduplicated chunks covering setup, turn structure, and scoring/win
    condition - the backbone of the pre-session digest."""
    cache_key = (game_slug, per_query_k)
    cached = _digest_cache.get(cache_key)
    if cached is not None:
        return [chunk.copy() for chunk in cached]

    seen = set()
    chunks: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(DIGEST_QUERIES)) as executor:
        future_map = {
            executor.submit(retrieve_chunks_for_game, game_slug, query, per_query_k): query
            for query in DIGEST_QUERIES
        }
        results_by_query: dict[str, list[dict]] = {}
        for future, query in future_map.items():
            results_by_query[query] = future.result()

    for query in DIGEST_QUERIES:
        for chunk in results_by_query.get(query, []):
            key = (chunk["page"], chunk["text"][:50])
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)
    _digest_cache[cache_key] = [chunk.copy() for chunk in chunks]
    return chunks


def retrieve_followup_chunks(game_slug: str, question: str, k: int = 5) -> list[dict]:
    normalized_question = " ".join(question.split()).casefold()
    cache_key = (game_slug, normalized_question, k)
    cached = _followup_cache.get(cache_key)
    if cached is not None:
        return [chunk.copy() for chunk in cached]

    chunks = retrieve_chunks_for_game(game_slug, question, k=k)
    _followup_cache[cache_key] = [chunk.copy() for chunk in chunks]
    return chunks
