"""Chunking strategies for KB documents.

Two strategies, dispatched by `doc_type` — the same factory/strategy shape as
`get_chat_model()` in `app/core/llm.py`: callers never pick a strategy directly,
`chunk_document()` does it for them based on the document's `doc_type`.

- `chunk_by_section`: splits on markdown `##` headers, one chunk per section. Used
  for content that's naturally atomic per section (FAQ, policy, billing) — a
  fixed-size cut risks splitting a question from its answer, or a rule from its
  exception.
- `chunk_by_fixed_size`: splits into fixed-size word windows with overlap. Used for
  longer, less-structured prose (features, integrations, security) with no
  reliable per-section boundary, and as the fallback inside `chunk_by_section` for
  any individual section that turns out to be unusually long.

`max_tokens` here is a word count, not a real provider tokenizer count: this
project supports three LLM providers (Claude, Gemini, Ollama), each with its own
tokenizer, so there's no single "correct" token count to target. Word count is a
transparent, provider-agnostic proxy for chunk size — not meant to be exact.
"""

import re

from app.schemas.rag import Chunk, DocType, SourceDocument

_SECTION_BASED_TYPES = {DocType.FAQ, DocType.POLICY, DocType.BILLING}

_SECTION_HEADER_RE = re.compile(r"^## +(.+)$", re.MULTILINE)


def chunk_document(document: SourceDocument) -> list[Chunk]:
    """Dispatch to the right chunking strategy based on `document.doc_type`."""
    if document.doc_type in _SECTION_BASED_TYPES:
        return chunk_by_section(document)
    return chunk_by_fixed_size(document)


def chunk_by_section(document: SourceDocument, max_tokens: int = 500) -> list[Chunk]:
    """Split on markdown `##` headers, one chunk per section.

    Content before the first `##` header (a title, a disclaimer line) becomes its
    own leading chunk with no `section_title` metadata. If a section's word count
    exceeds `max_tokens`, that section alone falls back to a fixed-size split
    instead of becoming one oversized, low-precision chunk.
    """
    sections = _split_into_sections(document.content)

    pieces: list[tuple[str, dict]] = []
    for section_title, text in sections:
        metadata = {"section_title": section_title} if section_title else {}
        words = text.split()
        if len(words) > max_tokens:
            for window in _windows_from_words(words, max_tokens=max_tokens, overlap=max_tokens // 10):
                pieces.append((window, metadata))
        else:
            pieces.append((text, metadata))

    return [Chunk(content=content, chunk_index=i, metadata=metadata) for i, (content, metadata) in enumerate(pieces)]


def _split_into_sections(content: str) -> list[tuple[str | None, str]]:
    """Return (section_title, section_text) pairs. `section_title` is `None` for
    any content preceding the first `##` header."""
    headers = list(_SECTION_HEADER_RE.finditer(content))
    if not headers:
        return [(None, content.strip())] if content.strip() else []

    sections: list[tuple[str | None, str]] = []

    preamble = content[: headers[0].start()].strip()
    if preamble:
        sections.append((None, preamble))

    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        sections.append((header.group(1).strip(), content[header.start() : end].strip()))

    return sections


def chunk_by_fixed_size(document: SourceDocument, max_tokens: int = 500, overlap: int = 50) -> list[Chunk]:
    """Split into fixed-size word windows with `overlap` words shared between
    consecutive chunks, so a sentence split across a chunk boundary still has
    context on both sides.

    Each window's words are rejoined with a single space, so exact original
    whitespace and markdown formatting is not preserved — acceptable for
    embeddings, which index meaning, not layout.
    """
    windows = _windows_from_words(document.content.split(), max_tokens=max_tokens, overlap=overlap)
    return [Chunk(content=window, chunk_index=i, metadata={}) for i, window in enumerate(windows)]


def _windows_from_words(words: list[str], max_tokens: int, overlap: int) -> list[str]:
    """Slide a `max_tokens`-word window over an already-split word list. Takes
    `words`, not raw text, so a caller that already split the text to check its
    length (`chunk_by_section`'s oversized-section check) doesn't split it again."""
    if not words:
        return []

    step = max(max_tokens - overlap, 1)
    windows = []
    start = 0
    while True:
        window = words[start : start + max_tokens]
        windows.append(" ".join(window))
        if start + max_tokens >= len(words):
            break
        start += step

    return windows
