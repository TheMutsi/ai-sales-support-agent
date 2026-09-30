"""Unit tests for the chunking strategies.

Chunking is deterministic (text in, list[Chunk] out), so these are pure
input/output tests — no fixtures, DB, or network involved.
"""

from app.rag.chunker import chunk_by_fixed_size, chunk_by_section, chunk_document
from app.schemas.rag import DocType, SourceDocument


def _document(doc_type: DocType, content: str) -> SourceDocument:
    return SourceDocument(title="Test", doc_type=doc_type, source="test.md", content=content)


def test_chunk_document_dispatches_policy_to_chunk_by_section():
    document = _document(DocType.POLICY, "Preamble.\n\n## One\nContent one.\n\n## Two\nContent two.")

    chunks = chunk_document(document)

    assert [c.metadata.get("section_title") for c in chunks] == [None, "One", "Two"]


def test_chunk_document_dispatches_features_to_chunk_by_fixed_size():
    document = _document(DocType.FEATURES, " ".join(f"word{i}" for i in range(20)))

    chunks = chunk_document(document)

    assert all("section_title" not in c.metadata for c in chunks)


def test_chunk_by_section_splits_on_h2_headers_only():
    document = _document(
        DocType.POLICY,
        "## First\nFirst body.\n\n### Not a split point\nStill first section.\n\n## Second\nSecond body.",
    )

    chunks = chunk_by_section(document)

    assert len(chunks) == 2
    assert chunks[0].metadata["section_title"] == "First"
    assert "### Not a split point" in chunks[0].content
    assert chunks[1].metadata["section_title"] == "Second"


def test_chunk_by_section_keeps_preamble_as_untitled_first_chunk():
    document = _document(DocType.POLICY, "Title and disclaimer.\n\n## Only section\nBody.")

    chunks = chunk_by_section(document)

    assert chunks[0].metadata == {}
    assert chunks[0].content == "Title and disclaimer."
    assert chunks[0].chunk_index == 0


def test_chunk_by_section_with_no_headers_returns_single_chunk():
    document = _document(DocType.POLICY, "Just plain content, no headers at all.")

    chunks = chunk_by_section(document)

    assert len(chunks) == 1
    assert chunks[0].metadata == {}


def test_chunk_by_section_falls_back_to_fixed_size_for_oversized_section():
    long_body = " ".join(f"word{i}" for i in range(120))
    document = _document(DocType.POLICY, f"## Long section\n{long_body}")

    chunks = chunk_by_section(document, max_tokens=50)

    assert len(chunks) == 3
    assert all(c.metadata["section_title"] == "Long section" for c in chunks)
    # "## Long section" (3 words) + 120 body words = 123 total; overlap = 50 // 10 = 5,
    # so the step is 45 words per window: [0:50], [45:95], [90:123].
    assert [len(c.content.split()) for c in chunks] == [50, 50, 33]


def test_chunk_index_is_sequential_across_fallback_sub_chunks():
    long_body = " ".join(f"word{i}" for i in range(120))
    document = _document(DocType.POLICY, f"## Short\nshort.\n\n## Long\n{long_body}\n\n## Short again\nshort.")

    chunks = chunk_by_section(document, max_tokens=50)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_by_fixed_size_overlaps_consecutive_windows():
    document = _document(DocType.FEATURES, " ".join(f"w{i}" for i in range(25)))

    chunks = chunk_by_fixed_size(document, max_tokens=10, overlap=3)

    assert [c.content for c in chunks] == [
        "w0 w1 w2 w3 w4 w5 w6 w7 w8 w9",
        "w7 w8 w9 w10 w11 w12 w13 w14 w15 w16",
        "w14 w15 w16 w17 w18 w19 w20 w21 w22 w23",
        "w21 w22 w23 w24",
    ]


def test_chunk_by_fixed_size_on_short_content_returns_one_chunk():
    document = _document(DocType.FEATURES, "just a few words")

    chunks = chunk_by_fixed_size(document, max_tokens=50, overlap=5)

    assert len(chunks) == 1
    assert chunks[0].content == "just a few words"


def test_chunk_by_fixed_size_on_empty_content_returns_no_chunks():
    document = _document(DocType.FEATURES, "   ")

    assert chunk_by_fixed_size(document) == []
