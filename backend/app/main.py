from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.observability import configure_langsmith

settings = get_settings()
configure_langsmith()

app = FastAPI(title="AcmeFlow Agent API", version=settings.app_version)

app.include_router(health_router, prefix="/api")
