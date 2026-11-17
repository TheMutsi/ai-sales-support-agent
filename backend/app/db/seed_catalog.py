import json
import uuid

from sqlalchemy.orm import Session

from app.core.config import SEED_DIR
from app.db.models import (
    ItemOffer,
    ItemTag,
    RecommendationItem,
    RecommendationTag,
    RecommendationType,
)


def _load_catalog() -> dict:
    return json.loads((SEED_DIR / "catalog.json").read_text())


def seed_demo_catalog(db: Session, tenant_id: uuid.UUID) -> None:
    catalog = _load_catalog()
    types = _ensure_types(db, tenant_id, catalog["types"])
    tags = _ensure_tags(db, tenant_id, catalog["tags"])
    existing = {
        item.external_id
        for item in db.query(RecommendationItem).filter_by(tenant_id=tenant_id)
    }
    for entry in catalog["items"]:
        if entry["external_id"] in existing:
            continue
        _add_item(db, tenant_id, entry, types[entry["type"]], tags)


def _ensure_types(db: Session, tenant_id: uuid.UUID, entries: list[dict]) -> dict[str, RecommendationType]:
    types = {t.key: t for t in db.query(RecommendationType).filter_by(tenant_id=tenant_id)}
    for entry in entries:
        if entry["key"] not in types:
            types[entry["key"]] = RecommendationType(tenant_id=tenant_id, **entry)
            db.add(types[entry["key"]])
    db.flush()
    return types


def _ensure_tags(db: Session, tenant_id: uuid.UUID, entries: list[dict]) -> dict[str, RecommendationTag]:
    tags = {t.slug: t for t in db.query(RecommendationTag).filter_by(tenant_id=tenant_id)}
    for entry in entries:
        if entry["slug"] not in tags:
            tags[entry["slug"]] = RecommendationTag(tenant_id=tenant_id, **entry)
            db.add(tags[entry["slug"]])
    db.flush()
    return tags


def _add_item(
    db: Session,
    tenant_id: uuid.UUID,
    entry: dict,
    item_type: RecommendationType,
    tags: dict[str, RecommendationTag],
) -> None:
    fields = {k: v for k, v in entry.items() if k not in {"type", "tags", "offers"}}
    item = RecommendationItem(tenant_id=tenant_id, type_id=item_type.id, status="active", **fields)
    db.add(item)
    db.flush()
    for offer in entry["offers"]:
        db.add(ItemOffer(item_id=item.id, tenant_id=tenant_id, **offer))
    for tag in entry["tags"]:
        db.add(
            ItemTag(
                item_id=item.id,
                tag_id=tags[tag["slug"]].id,
                tenant_id=tenant_id,
                weight=tag["weight"],
                why=tag["why"],
                pinned=tag.get("pinned", False),
                is_complement=tag.get("is_complement", False),
            )
        )
    db.flush()
