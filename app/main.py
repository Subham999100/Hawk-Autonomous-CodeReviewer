import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.sse import router as sse_router
from app.api.tasks import router as tasks_router, create_task as api_create_task
from app.core.config import settings
from app.db.session import engine, init_db
from app.models.task import TaskRequest
from app.services.github_client import GitHubClientError, get_repository_metadata
from app.services.jev_service import orchestrate_investigation_triage
from app.services.obsidian_service import sync_investigation_memory
from app.services.queue_service import get_redis_client
from app.services.reasoning_service import analyze_engineering_evidence
from app.services.repository_evidence import collect_repository_evidence

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hawk.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and seed initial admin user
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as exc:
        logger.error("Failed to initialize database: %s", exc)

    # Check Redis connection
    redis = await get_redis_client()
    if redis:
        logger.info("Redis queue connected at %s", settings.redis_url)
    else:
        logger.info("Redis unavailable; active in-memory queue fallback.")

    yield

    logger.info("Hawk application shutting down.")


app = FastAPI(
    title=settings.app_name,
    description="Autonomous Engineering Investigation Platform",
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(auth_router)
app.include_router(tasks_router)
app.include_router(sse_router)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/health/details")
@app.get("/health/ready")
async def health_details():
    """Detailed health check for database and redis monitoring."""
    db_status = "healthy"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"unhealthy: {str(exc)}"

    redis_client = await get_redis_client()
    redis_status = "connected" if redis_client else "in_memory_fallback"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "database": db_status,
        "redis": redis_status,
        "auth": settings.auth_provider,
        "orchestration": "jev_systemone",
        "memory": "obsidian_rest",
    }
