"""Extract token-bounded chunks from a rulebook PDF.

Each chunk stays within a single page (one chunk = one page range) so
retrieval can stay aligned to the source document without mixing content
across pages.
"""

import pymupdf as fitz
import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")


def _token_len(text: str) -> int:
    return len(_encoding.encode(text))


def _tail_by_tokens(text: str, n_tokens: int) -> str:
    tokens = _encoding.encode(text)
    if len(tokens) <= n_tokens:
        return text
    return _encoding.decode(tokens[-n_tokens:])


def extract_page_chunks(pdf_path, target_tokens: int = 650, overlap_tokens: int = 100):
    """Return a list of {"text": str, "page": int} chunks, page numbers 1-indexed."""
    doc = fitz.open(pdf_path)
    chunks = []
    try:
        for page_index in range(len(doc)):
            page_number = page_index + 1
            text = doc[page_index].get_text("text").strip()
            if not text:
                continue

            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()] or [text]

            current: list[str] = []
            current_tokens = 0
            for para in paragraphs:
                para_tokens = _token_len(para)
                if current and current_tokens + para_tokens > target_tokens:
                    chunk_text = "\n\n".join(current)
                    chunks.append({"text": chunk_text, "page": page_number})
                    overlap_text = _tail_by_tokens(chunk_text, overlap_tokens)
                    current = [overlap_text] if overlap_text else []
                    current_tokens = _token_len(overlap_text) if overlap_text else 0
                current.append(para)
                current_tokens += para_tokens

            if current:
                chunks.append({"text": "\n\n".join(current), "page": page_number})
    finally:
        doc.close()

    return chunks
