"""CLI: build the Pinecone vector index for the v1 pilot rulebooks.

Usage:
    python -m app.ingestion.ingest
"""

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from app.config import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    PILOT_GAMES,
    PINECONE_API_KEY,
    PINECONE_CLOUD,
    PINECONE_INDEX_NAME,
    PINECONE_REGION,
    RULEBOOKS_DIR,
)
from app.ingestion.parse_pdf import extract_page_chunks


def build_documents_for_game(game: dict) -> tuple[list[Document], list[str]]:
    """Docs plus a matching list of deterministic IDs (game_slug:page:index
    within that page - a page can produce multiple chunks). Deterministic
    IDs make ingestion idempotent: Pinecone upserts by ID, so re-running this
    for a game overwrites its existing vectors in place instead of piling up
    duplicates alongside them - important since this runs across the whole
    library each time, including games already ingested in a prior run."""
    pdf_path = RULEBOOKS_DIR / game["rulebook_file"]
    chunks = extract_page_chunks(pdf_path)

    docs: list[Document] = []
    ids: list[str] = []
    chunk_index_by_page: dict[int, int] = {}
    for chunk in chunks:
        page = chunk["page"]
        index_on_page = chunk_index_by_page.get(page, 0)
        chunk_index_by_page[page] = index_on_page + 1

        docs.append(Document(
            page_content=chunk["text"],
            metadata={
                "game_slug": game["slug"],
                "game_name": game["name"],
                "bgg_id": game["bgg_id"],
                "page": page,
            },
        ))
        ids.append(f"{game['slug']}:p{page}:{index_on_page}")

    return docs, ids


def _ensure_index(pc: Pinecone) -> None:
    if PINECONE_INDEX_NAME in pc.list_indexes().names():
        return
    pc.create_index(
        name=PINECONE_INDEX_NAME,
        dimension=EMBEDDING_DIMENSIONS,
        metric="cosine",
        spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
    )


def main() -> None:
    all_docs: list[Document] = []
    all_ids: list[str] = []
    for game in PILOT_GAMES:
        docs, ids = build_documents_for_game(game)
        print(f"{game['name']}: {len(docs)} chunks from {game['rulebook_file']}")
        all_docs.extend(docs)
        all_ids.extend(ids)

    pc = Pinecone(api_key=PINECONE_API_KEY)
    _ensure_index(pc)

    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL, dimensions=EMBEDDING_DIMENSIONS)
    PineconeVectorStore.from_documents(
        documents=all_docs,
        embedding=embeddings,
        index_name=PINECONE_INDEX_NAME,
        ids=all_ids,
    )
    print(f"Upserted {len(all_docs)} chunks into Pinecone index '{PINECONE_INDEX_NAME}'")


if __name__ == "__main__":
    main()
