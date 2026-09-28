from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="AcmeFlow Agent API", version=settings.app_version)

app.include_router(health_router, prefix="/api")
