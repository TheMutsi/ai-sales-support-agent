from sqlalchemy.orm import Session

from app.core.config import LOCAL_ENVIRONMENTS, get_settings
from app.db.models import Tenant, TenantSecret

DEV_TENANT_API_KEY = "pk_dev_mewflow_local"
DEV_TENANT_SECRET = "dev-only-tenant-secret-never-use-in-production"
DEV_TENANT_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
]
DEV_TENANT_KID = "dev-1"


def ensure_dev_tenant(db: Session) -> Tenant | None:
    if get_settings().app_env not in LOCAL_ENVIRONMENTS:
        return None
    tenant = db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one_or_none()
    if tenant is None:
        tenant = Tenant(name="Local development shop", api_key=DEV_TENANT_API_KEY)
        db.add(tenant)
        db.flush()
    tenant.allowed_origins = DEV_TENANT_ORIGINS
    secret = db.query(TenantSecret).filter_by(tenant_id=tenant.id, kid=DEV_TENANT_KID).one_or_none()
    if secret is None:
        db.add(TenantSecret(tenant_id=tenant.id, kid=DEV_TENANT_KID, secret=DEV_TENANT_SECRET))
    else:
        secret.secret, secret.active = DEV_TENANT_SECRET, True
    return tenant
