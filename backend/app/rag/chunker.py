import re

from app.schemas.rag import Chunk, DocType, SourceDocument

_SECTION_BASED_TYPES = {DocType.FAQ, DocType.POLICY, DocType.BILLING}

_SECTION_HEADER_RE = re.compile(r"^## +(.+)$", re.MULTILINE)


def chunk_document(document: SourceDocument) -> list[Chunk]:
    if document.doc_type in _SECTION_BASED_TYPES:
        return chunk_by_section(document)
    return chunk_by_fixed_size(document)


def chunk_by_section(document: SourceDocument, max_words: int = 500) -> list[Chunk]:
    sections = _split_into_sections(document.content)

    pieces: list[tuple[str, dict]] = []
    for section_title, text in sections:
        metadata = {"section_title": section_title} if section_title else {}
        words = text.split()
        if len(words) > max_words:
            for window in _windows_from_words(words, max_words=max_words, overlap=max_words // 10):
                pieces.append((window, metadata))
        else:
            pieces.append((text, metadata))

    return [Chunk(content=content, chunk_index=i, metadata=metadata) for i, (content, metadata) in enumerate(pieces)]


def _split_into_sections(content: str) -> list[tuple[str | None, str]]:
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


def chunk_by_fixed_size(document: SourceDocument, max_words: int = 500, overlap: int = 50) -> list[Chunk]:
    windows = _windows_from_words(document.content.split(), max_words=max_words, overlap=overlap)
    return [Chunk(content=window, chunk_index=i, metadata={}) for i, window in enumerate(windows)]


def _windows_from_words(words: list[str], max_words: int, overlap: int) -> list[str]:
    if not words:
        return []

    step = max(max_words - overlap, 1)
    windows = []
    start = 0
    while True:
        window = words[start : start + max_words]
        windows.append(" ".join(window))
        if start + max_words >= len(words):
            break
        start += step

    return windows
