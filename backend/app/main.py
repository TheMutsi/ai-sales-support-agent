import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.customers import router as customers_router
from app.api.health import router as health_router
from app.api.origins import TenantCORSMiddleware
from app.core.config import get_settings
from app.core.observability import configure_langfuse
from app.core.tenant_config import TenantConfigUnavailable

# Only the app's own messages at INFO (the local one-time code is one); libraries stay at
# WARNING so they don't flood the console.
logging.basicConfig(level=logging.WARNING)
logging.getLogger("app").setLevel(logging.INFO)

settings = get_settings()
configure_langfuse()

app = FastAPI(title="MewFlow Agent API", version=settings.app_version)

app.add_middleware(
    TenantCORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

@app.exception_handler(TenantConfigUnavailable)
async def _configuration_unavailable(request: Request, exc: TenantConfigUnavailable):
    """The shop's configuration could not be read and cannot be guessed (an unknown shop would skip
    the origin check, missing scope overrides could widen what a visitor may do): fail closed."""
    return JSONResponse(status_code=503, content={"detail": {"code": "configuration_unavailable"}})


app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(customers_router, prefix="/api")
