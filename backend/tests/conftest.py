from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# A real sample PDF used by document-upload tests, shared so the file path and
# read-into-bytes logic isn't duplicated across test modules.
SAMPLE_PDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "sample-docs", "title-report-lot-7.pdf"
)


def read_sample_pdf_bytes() -> bytes:
    """Read the shared sample PDF's raw bytes."""
    with open(SAMPLE_PDF_PATH, "rb") as f:
        return f.read()


# Point the app at a dedicated test database *before* importing anything that
# reads `takehome.config.settings` at import time.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://orbital:orbital@localhost:5556/orbital_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# The messages router imports takehome.services.llm at module load time, which
# constructs a pydantic-ai Agent that requires an Anthropic API key to exist
# (it is never actually called in these tests). A placeholder is enough.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder-key")

from takehome.db.models import Base  # noqa: E402
from takehome.db.session import get_session  # noqa: E402

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _reset_database() -> AsyncGenerator[None, None]:
    """Create a clean schema before each test and drop it afterward."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as db_session:
        yield db_session


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client wired to the FastAPI app, without running migrations
    on app startup (schema is managed directly by `_reset_database`)."""
    from takehome.web.app import app

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with TestSessionLocal() as db_session:
            yield db_session

    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_session, None)
