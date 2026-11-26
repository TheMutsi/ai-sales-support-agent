import logging
import uuid

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.business.tag_registry import cosine_similarity
from app.core.embeddings import get_embeddings
from app.core.llm import get_chat_model
from app.db.models import ItemTag, RecommendationItem, RecommendationTag
from app.recommendations.prompts import BACKFILL_SYSTEM_PROMPT, render_backfill_prompt
from app.schemas.recommendations import BackfillResult, TagFit

logger = logging.getLogger(__name__)

NEIGHBOUR_TAGS = 3
NEAREST_ITEMS = 10
MAX_CANDIDATES = 20


def _lock_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"enrich:{tenant_id}"})


def _neighbour_tag_ids(session: Session, tag: RecommendationTag) -> list[uuid.UUID]:
    others = session.scalars(
        select(RecommendationTag).where(
            RecommendationTag.tenant_id == tag.tenant_id,
            RecommendationTag.id != tag.id,
            RecommendationTag.embedding.is_not(None),
        )
    ).all()
    ranked = sorted(others, key=lambda other: (-cosine_similarity(tag.embedding, other.embedding), other.slug))
    return [other.id for other in ranked[:NEIGHBOUR_TAGS]]


def candidate_item_ids(session: Session, tag: RecommendationTag) -> list[uuid.UUID]:
    holding = set(
        session.scalars(
            select(ItemTag.item_id).where(
                ItemTag.tenant_id == tag.tenant_id, ItemTag.tag_id.in_(_neighbour_tag_ids(session, tag))
            )
        )
    )
    nearest = session.scalars(
        select(RecommendationItem.id)
        .where(
            RecommendationItem.tenant_id == tag.tenant_id,
            RecommendationItem.status == "active",
            RecommendationItem.embedding.is_not(None),
        )
        .order_by(RecommendationItem.embedding.cosine_distance(tag.embedding), RecommendationItem.id)
        .limit(NEAREST_ITEMS)
    ).all()
    already = set(session.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == tag.id)))
    ordered = sorted(holding | set(nearest), key=str)
    return [item_id for item_id in ordered if item_id not in already][:MAX_CANDIDATES]


def backfill_tag(
    session: Session,
    tenant_id: uuid.UUID,
    tag_id: uuid.UUID,
    *,
    llm: BaseChatModel | None = None,
    embeddings: Embeddings | None = None,
) -> BackfillResult:
    llm = llm or get_chat_model()
    embeddings = embeddings or get_embeddings()
    tag = session.scalars(
        select(RecommendationTag).where(RecommendationTag.id == tag_id, RecommendationTag.tenant_id == tenant_id)
    ).one()
    if tag.embedding is None:
        tag.embedding = embeddings.embed_query(tag.description or tag.slug)
    result = BackfillResult(tag=tag.slug)
    _lock_tenant(session, tenant_id)
    structured = llm.with_structured_output(TagFit).with_retry(stop_after_attempt=3)
    for item_id in candidate_item_ids(session, tag):
        item = session.get(RecommendationItem, item_id)
        result.checked += 1
        try:
            fit = structured.invoke(
                [
                    SystemMessage(content=BACKFILL_SYSTEM_PROMPT),
                    HumanMessage(
                        content=render_backfill_prompt(
                            tag.slug, tag.description, item.title, item.short_desc, item.long_desc
                        )
                    ),
                ]
            )
        except Exception:
            logger.exception("tag backfill failed", extra={"item_id": str(item_id), "tag": tag.slug})
            result.failed.append(item.external_id)
            continue
        if fit.applies:
            session.add(
                ItemTag(item_id=item.id, tag_id=tag.id, tenant_id=tenant_id, weight=fit.weight, why=fit.why)
            )
            result.tagged.append(item.external_id)
    session.commit()
    return result
