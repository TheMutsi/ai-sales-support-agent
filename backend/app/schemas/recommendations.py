from pydantic import BaseModel, Field

MAX_TAGS_PER_ITEM = 8


class TagAssignment(BaseModel):
    slug: str = Field(min_length=1)
    description: str = ""
    weight: float = Field(ge=0, le=1)
    why: str = ""


class ItemEnrichment(BaseModel):
    tags: list[TagAssignment] = Field(default_factory=list, max_length=MAX_TAGS_PER_ITEM)
    complement_tags: list[TagAssignment] = Field(default_factory=list, max_length=MAX_TAGS_PER_ITEM)


class EnrichmentResult(BaseModel):
    item_id: str
    status: str
    created_tags: list[str] = Field(default_factory=list)
    reused_tags: list[str] = Field(default_factory=list)
    error: str | None = None
