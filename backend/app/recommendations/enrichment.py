import logging
import uuid

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.business.tag_registry import find_near_duplicate, normalize_slug
from app.core.embeddings import get_embeddings
from app.core.llm import get_chat_model
from app.db.models import ItemTag, RecommendationItem, RecommendationTag
from app.recommendations.prompts import ENRICHMENT_SYSTEM_PROMPT, render_item_prompt
from app.schemas.recommendations import EnrichmentResult, ItemEnrichment, TagAssignment

logger = logging.getLogger(__name__)

ENRICHED = "ready"
FAILED = "failed"
ENRICHMENT_FAILED_MESSAGE = "enrichment failed; see the logs for the cause"


def _item_text(item: RecommendationItem) -> str:
    return " ".join(part for part in (item.title, item.short_desc, item.long_desc) if part)


def _lock_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"enrich:{tenant_id}"})


def _registry(session: Session, tenant_id: uuid.UUID, embeddings: Embeddings) -> dict[str, RecommendationTag]:
    tags = {tag.slug: tag for tag in session.scalars(select(RecommendationTag).where(RecommendationTag.tenant_id == tenant_id))}
    missing = [tag for tag in tags.values() if tag.embedding is None]
    if missing:
        vectors = embeddings.embed_documents([tag.description or tag.slug for tag in missing])
        if len(vectors) != len(missing):
            raise ValueError("the embedding provider returned a different number of vectors than requested")
        for tag, vector in zip(missing, vectors):
            tag.embedding = vector
    return tags


def _resolve_tag(
    session: Session,
    tenant_id: uuid.UUID,
    assignment: TagAssignment,
    registry: dict[str, RecommendationTag],
    embeddings: Embeddings,
    created: list[str],
) -> RecommendationTag | None:
    try:
        slug = normalize_slug(assignment.slug)
    except ValueError:
        logger.warning("skipping a tag with no usable slug", extra={"slug": assignment.slug})
        return None
    if slug in registry:
        return registry[slug]
    description = assignment.description or slug.replace("-", " ")
    vector = embeddings.embed_query(description)
    known = {tag_slug: tag.embedding for tag_slug, tag in registry.items() if tag.embedding is not None}
    duplicate = find_near_duplicate(vector, known)
    if duplicate is not None:
        return registry[duplicate]
    tag = RecommendationTag(tenant_id=tenant_id, slug=slug, description=description, embedding=vector)
    session.add(tag)
    session.flush()
    registry[slug] = tag
    created.append(slug)
    return tag


def _replace_item_tags(
    session: Session,
    item: RecommendationItem,
    enrichment: ItemEnrichment,
    registry: dict[str, RecommendationTag],
    embeddings: Embeddings,
    created: list[str],
    reused: list[str],
) -> None:
    pinned = {row.tag_id for row in session.scalars(select(ItemTag).where(ItemTag.item_id == item.id, ItemTag.pinned))}
    session.execute(delete(ItemTag).where(ItemTag.item_id == item.id, ItemTag.pinned.is_(False)))
    written: dict[uuid.UUID, ItemTag] = {}
    for assignments, is_complement in ((enrichment.tags, False), (enrichment.complement_tags, True)):
        for assignment in assignments:
            before = len(created)
            tag = _resolve_tag(session, item.tenant_id, assignment, registry, embeddings, created)
            if tag is None or tag.id in pinned:
                continue
            existing = written.get(tag.id)
            if existing is not None:
                if assignment.weight > existing.weight:
                    existing.weight = assignment.weight
                    existing.why = assignment.why
                continue
            if len(created) == before:
                reused.append(tag.slug)
            link = ItemTag(
                item_id=item.id,
                tag_id=tag.id,
                tenant_id=item.tenant_id,
                weight=assignment.weight,
                why=assignment.why,
                is_complement=is_complement,
            )
            session.add(link)
            written[tag.id] = link
    session.flush()


def _mark_failed(session: Session, tenant_id: uuid.UUID, item_id: uuid.UUID) -> EnrichmentResult:
    session.rollback()
    session.execute(
        update(RecommendationItem)
        .where(RecommendationItem.id == item_id, RecommendationItem.tenant_id == tenant_id)
        .values(enrichment_status=FAILED)
    )
    session.commit()
    return EnrichmentResult(item_id=str(item_id), status=FAILED, error=ENRICHMENT_FAILED_MESSAGE)


def enrich_item(
    session: Session,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    llm: BaseChatModel | None = None,
    embeddings: Embeddings | None = None,
) -> EnrichmentResult:
    llm = llm or get_chat_model()
    embeddings = embeddings or get_embeddings()
    try:
        _lock_tenant(session, tenant_id)
        item = session.scalars(
            select(RecommendationItem).where(RecommendationItem.id == item_id, RecommendationItem.tenant_id == tenant_id)
        ).one()
        registry = _registry(session, tenant_id, embeddings)
        prompt = render_item_prompt(
            item.title, item.short_desc, item.long_desc, {slug: tag.description for slug, tag in registry.items()}
        )
        structured = llm.with_structured_output(ItemEnrichment).with_retry(stop_after_attempt=3)
        enrichment = structured.invoke([SystemMessage(content=ENRICHMENT_SYSTEM_PROMPT), HumanMessage(content=prompt)])
        created: list[str] = []
        reused: list[str] = []
        _replace_item_tags(session, item, enrichment, registry, embeddings, created, reused)
        item.embedding = embeddings.embed_query(_item_text(item))
        item.enrichment_status = ENRICHED
        session.commit()
        return EnrichmentResult(item_id=str(item_id), status=ENRICHED, created_tags=created, reused_tags=reused)
    except Exception:
        logger.exception("item enrichment failed", extra={"item_id": str(item_id)})
        return _mark_failed(session, tenant_id, item_id)
