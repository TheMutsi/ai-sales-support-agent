from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.customers import router as customers_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.observability import configure_langfuse

settings = get_settings()
configure_langfuse()

app = FastAPI(title="AcmeFlow Agent API", version=settings.app_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(customers_router, prefix="/api")
