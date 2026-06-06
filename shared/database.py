from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from shared.config import settings

# pool_pre_ping issues a lightweight liveness check when a connection is
# checked out of the pool and transparently replaces a dead one, so a
# connection that went stale while idle (a postgres restart, a network
# blip, or a long gap between bursts of work) never surfaces as a
# ConnectionDoesNotExistError to the caller. pool_recycle proactively
# retires connections older than 30 minutes, staying ahead of any
# server-side idle timeout. Both matter for long-running workers that sit
# idle between events and then make slow VLM/STT calls.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session
