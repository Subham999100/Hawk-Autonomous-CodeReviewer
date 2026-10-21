import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Base, User

logger = logging.getLogger("hawk.db")

# Create engine
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args=connect_args,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initializes tables and seeds default user if none exists."""
    from app.core.auth import get_password_hash

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        existing_user = result.scalar_one_or_none()
        if not existing_user:
            demo_user = User(
                email="engineer@hawk.local",
                hashed_password=get_password_hash("HawkPass123!"),
                name="Principal Engineer",
                role="admin",
            )
            session.add(demo_user)
            await session.commit()
            logger.info("Initialized database with default admin user: engineer@hawk.local")
