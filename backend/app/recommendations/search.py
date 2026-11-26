import logging
import uuid
from collections import defaultdict

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.business.recommendations import MAX_RECOMMENDATIONS, Candidate, rank_by_tags
from app.business.tag_search import fuse_rankings, is_weak, validate_selection
from app.core.embeddings import get_embeddings
from app.core.llm import get_chat_model
from app.db.models import ItemTag, RecommendationItem, RecommendationTag
from app.recommendations.prompts import SEARCH_SYSTEM_PROMPT, render_search_prompt
from app.schemas.recommendations import SearchHit, TagSelection

logger = logging.getLogger(__name__)

CANDIDATES_PER_RANKING = 20


def _registry(session: Session, tenant_id: uuid.UUID) -> dict[str, str]:
    rows = session.execute(
        select(RecommendationTag.slug, RecommendationTag.description).where(RecommendationTag.tenant_id == tenant_id)
    )
    return dict(rows.all())


def _select_tags(llm: BaseChatModel, query: str, registry: dict[str, str]) -> list[str]:
    if not registry:
        return []
    structured = llm.with_structured_output(TagSelection).with_retry(stop_after_attempt=3)
    selection = structured.invoke(
        [SystemMessage(content=SEARCH_SYSTEM_PROMPT), HumanMessage(content=render_search_prompt(query, registry))]
    )
    return validate_selection(selection.slugs, registry)


def _candidates(session: Session, tenant_id: uuid.UUID) -> list[Candidate]:
    weights: dict[uuid.UUID, dict[str, float]] = defaultdict(dict)
    links = session.execute(
        select(ItemTag.item_id, RecommendationTag.slug, ItemTag.weight)
        .join(RecommendationTag, RecommendationTag.id == ItemTag.tag_id)
        .join(RecommendationItem, RecommendationItem.id == ItemTag.item_id)
        .where(
            ItemTag.tenant_id == tenant_id,
            ItemTag.is_complement.is_(False),
            RecommendationItem.status == "active",
        )
    )
    for item_id, slug, weight in links:
        weights[item_id][slug] = weight
    return [Candidate(item_id=str(item_id), tag_weights=tag_weights) for item_id, tag_weights in weights.items()]


def _text_ranking(session: Session, tenant_id: uuid.UUID, query: str) -> list[str]:
    text_query = func.plainto_tsquery("simple", query)
    rank = func.ts_rank(RecommendationItem.search_tsv, text_query)
    rows = session.scalars(
        select(RecommendationItem.id)
        .where(
            RecommendationItem.tenant_id == tenant_id,
            RecommendationItem.status == "active",
            RecommendationItem.search_tsv.op("@@")(text_query),
        )
        .order_by(rank.desc(), RecommendationItem.id)
        .limit(CANDIDATES_PER_RANKING)
    )
    return [str(item_id) for item_id in rows]


def _vector_ranking(session: Session, tenant_id: uuid.UUID, vector: list[float]) -> list[str]:
    rows = session.scalars(
        select(RecommendationItem.id)
        .where(
            RecommendationItem.tenant_id == tenant_id,
            RecommendationItem.status == "active",
            RecommendationItem.embedding.is_not(None),
        )
        .order_by(RecommendationItem.embedding.cosine_distance(vector), RecommendationItem.id)
        .limit(CANDIDATES_PER_RANKING)
    )
    return [str(item_id) for item_id in rows]


def hybrid_search(
    session: Session, tenant_id: uuid.UUID, query: str, embeddings: Embeddings, limit: int
) -> list[SearchHit]:
    by_vector = _vector_ranking(session, tenant_id, embeddings.embed_query(query))
    by_text = _text_ranking(session, tenant_id, query)
    fused = fuse_rankings([by_vector, by_text])
    return [SearchHit(item_id=item_id, score=score, source="text") for item_id, score in fused[:limit]]


def search_items(
    session: Session,
    tenant_id: uuid.UUID,
    query: str,
    *,
    limit: int = MAX_RECOMMENDATIONS,
    llm: BaseChatModel | None = None,
    embeddings: Embeddings | None = None,
) -> list[SearchHit]:
    llm = llm or get_chat_model()
    embeddings = embeddings or get_embeddings()
    registry = _registry(session, tenant_id)
    try:
        wanted = _select_tags(llm, query, registry)
    except Exception:
        logger.exception("tag selection failed, falling back to text search", extra={"query_length": len(query)})
        wanted = []
    ranked = rank_by_tags(_candidates(session, tenant_id), frozenset(wanted), limit) if wanted else []
    if not is_weak(ranked):
        return [SearchHit(item_id=item.item_id, score=item.score, source="tags") for item in ranked]
    return hybrid_search(session, tenant_id, query, embeddings, limit)
