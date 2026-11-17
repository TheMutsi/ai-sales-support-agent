import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.embeddings import get_embeddings
from app.db.models import Document, DocumentChunk, DocumentVersion
from app.schemas.rag import DocType, RetrievedChunk

CANDIDATES_PER_RANKING = 20
RECIPROCAL_RANK_FUSION_K = 60
DEFAULT_MIN_SIMILARITY = 0.4
SECTION_SEPARATOR = "\n\n"


@dataclass(frozen=True)
class _Candidate:
    chunk_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_index: int
    chunk_metadata: dict
    document_id: uuid.UUID
    doc_type: str
    title: str
    source: str
    version: int
    content: str


def _published_chunks(
    columns: tuple,
    tenant_id: uuid.UUID,
    doc_type: DocType | None,
    plan_scope: str | None,
) -> Select:
    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_version_id,
            DocumentChunk.chunk_index,
            DocumentChunk.chunk_metadata,
            Document.id,
            Document.doc_type,
            Document.title,
            Document.source,
            DocumentVersion.version,
            DocumentChunk.content,
            *columns,
        )
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(Document, Document.published_version_id == DocumentVersion.id)
        .where(Document.tenant_id == tenant_id)
    )
    if doc_type is not None:
        statement = statement.where(Document.doc_type == doc_type.value)
    if plan_scope is None:
        return statement.where(Document.plan_scope.is_(None))
    statement = statement.where((Document.plan_scope == plan_scope) | Document.plan_scope.is_(None))
    return statement


def _candidate_of(row) -> _Candidate:
    return _Candidate(*row[:10])


def _vector_ranking(
    session: Session,
    query_vector: list[float],
    tenant_id: uuid.UUID,
    doc_type: DocType | None,
    plan_scope: str | None,
) -> list[tuple[_Candidate, float]]:
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    statement = (
        _published_chunks((distance,), tenant_id, doc_type, plan_scope)
        .where(DocumentChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(CANDIDATES_PER_RANKING)
    )
    return [(_candidate_of(row), 1 - row[10]) for row in session.execute(statement).all()]


def _full_text_ranking(
    session: Session,
    query: str,
    tenant_id: uuid.UUID,
    doc_type: DocType | None,
    plan_scope: str | None,
) -> list[_Candidate]:
    text_query = func.plainto_tsquery("simple", query)
    rank = func.ts_rank(DocumentChunk.content_tsv, text_query)
    statement = (
        _published_chunks((rank,), tenant_id, doc_type, plan_scope)
        .where(DocumentChunk.content_tsv.op("@@")(text_query))
        .order_by(rank.desc(), DocumentChunk.id)
        .limit(CANDIDATES_PER_RANKING)
    )
    return [_candidate_of(row) for row in session.execute(statement).all()]


def _fuse(rankings: list[list[uuid.UUID]]) -> dict[uuid.UUID, float]:
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RECIPROCAL_RANK_FUSION_K + position)
    return scores


def _section_title(candidate: _Candidate) -> str | None:
    return (candidate.chunk_metadata or {}).get("section_title")


def _sections_text(session: Session, version_ids: set[uuid.UUID]) -> dict[tuple[uuid.UUID, str], str]:
    rows = session.execute(
        select(DocumentChunk.document_version_id, DocumentChunk.chunk_metadata, DocumentChunk.content)
        .where(DocumentChunk.document_version_id.in_(version_ids))
        .order_by(DocumentChunk.document_version_id, DocumentChunk.chunk_index)
    ).all()
    parts: dict[tuple[uuid.UUID, str], list[str]] = {}
    for version_id, chunk_metadata, content in rows:
        title = (chunk_metadata or {}).get("section_title")
        if title is not None:
            parts.setdefault((version_id, title), []).append(content)
    return {key: SECTION_SEPARATOR.join(contents) for key, contents in parts.items()}


def search(
    session: Session,
    query: str,
    *,
    tenant_id: uuid.UUID,
    top_k: int = 5,
    doc_type: DocType | None = None,
    plan_scope: str | None = None,
    min_score: float = DEFAULT_MIN_SIMILARITY,
) -> list[RetrievedChunk]:
    query_vector = get_embeddings().embed_query(query)
    by_vector = _vector_ranking(session, query_vector, tenant_id, doc_type, plan_scope)
    by_text = _full_text_ranking(session, query, tenant_id, doc_type, plan_scope)

    candidates = {candidate.chunk_id: candidate for candidate, _ in by_vector}
    candidates.update({candidate.chunk_id: candidate for candidate in by_text})
    similarity = {candidate.chunk_id: value for candidate, value in by_vector}
    matched_words = {candidate.chunk_id for candidate in by_text}

    scores = _fuse([[c.chunk_id for c, _ in by_vector], [c.chunk_id for c in by_text]])
    relevant = [
        chunk_id
        for chunk_id in scores
        if chunk_id in matched_words or similarity.get(chunk_id, 0.0) >= min_score
    ]
    ordered = sorted(relevant, key=lambda chunk_id: (-scores[chunk_id], str(chunk_id)))

    seen: set[tuple] = set()
    chosen: list[_Candidate] = []
    for chunk_id in ordered:
        candidate = candidates[chunk_id]
        title = _section_title(candidate)
        key = (candidate.document_version_id, title) if title is not None else (chunk_id,)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(candidate)
        if len(chosen) == top_k:
            break

    sections = _sections_text(session, {candidate.document_version_id for candidate in chosen}) if chosen else {}
    results = []
    for candidate in chosen:
        title = _section_title(candidate)
        content = sections.get((candidate.document_version_id, title)) if title is not None else None
        results.append(
            RetrievedChunk(
                chunk_id=candidate.chunk_id,
                content=content if content is not None else candidate.content,
                metadata=candidate.chunk_metadata,
                document_id=candidate.document_id,
                doc_type=DocType(candidate.doc_type),
                document_title=candidate.title,
                source=candidate.source,
                score=scores[candidate.chunk_id],
                section=title,
                version=candidate.version,
            )
        )
    return results
