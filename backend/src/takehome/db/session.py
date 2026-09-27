from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from takehome.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """The session factory itself (not a single session), as a FastAPI
    dependency.

    Some request handlers (e.g. `messages.send_message`) need to open a
    *second*, independent session later in a background-style flow (a
    streamed response's generator, which keeps running after the
    request-scoped `session` from `get_session` may already be closed) --
    they can't just reuse the one `Depends(get_session)` gives them. Getting
    that second session via this dependency, instead of importing the
    `async_session` module attribute directly, keeps it swappable through
    FastAPI's dependency-override mechanism exactly like `get_session` is --
    otherwise a test overriding `get_session` to point at an isolated test
    database has no effect on this second session, which would silently keep
    talking to whatever engine this module was first imported with.
    """
    return async_session
