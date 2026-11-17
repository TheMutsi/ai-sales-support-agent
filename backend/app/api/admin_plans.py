import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.permissions import Permission
from app.admin.session import AdminSession
from app.api.admin_deps import require_tenant_permission
from app.db.models import Plan
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

_READ = require_tenant_permission(Permission.KB_READ)


class PlanOption(BaseModel):
    slug: str
    name: str


@router.get("/tenants/{tenant_id}/plans", response_model=list[PlanOption])
def list_plans(
    tenant_id: uuid.UUID,
    session: Annotated[AdminSession, Depends(_READ)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PlanOption]:
    plans = db.scalars(select(Plan).order_by(Plan.price_cents, Plan.slug)).all()
    return [PlanOption(slug=plan.slug, name=plan.name) for plan in plans]
