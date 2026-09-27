from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# A real sample PDF used by document-upload tests, shared so the file path and
# read-into-bytes logic isn't duplicated across test modules.
SAMPLE_PDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "sample-docs", "title-report-lot-7.pdf"
)

# All three of the project's real fixture PDFs, one per non-"other"
# `document_type` -- used by the upload-classification integration test (see
# issue #32's acceptance criteria) so it exercises the actual extraction +
# classification pipeline against real files rather than synthetic text.
SAMPLE_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "sample-docs")
SAMPLE_TITLE_PDF_PATH = os.path.join(SAMPLE_DOCS_DIR, "title-report-lot-7.pdf")
SAMPLE_LEASE_PDF_PATH = os.path.join(SAMPLE_DOCS_DIR, "commercial-lease-100-bishopsgate.pdf")
SAMPLE_ENVIRONMENTAL_PDF_PATH = os.path.join(
    SAMPLE_DOCS_DIR, "environmental-assessment-manchester.pdf"
)


def read_sample_pdf_bytes() -> bytes:
    """Read the shared sample PDF's raw bytes."""
    with open(SAMPLE_PDF_PATH, "rb") as f:
        return f.read()


def read_pdf_bytes(path: str) -> bytes:
    """Read an arbitrary fixture PDF's raw bytes."""
    with open(path, "rb") as f:
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

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

from takehome.db.models import Base, DocumentType  # noqa: E402
from takehome.db.session import get_session, get_session_factory  # noqa: E402
from takehome.services.llm import classification_agent  # noqa: E402

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


def make_classification_stub(
    document_type: DocumentType,
) -> Callable[[list[ModelMessage], AgentInfo], ModelResponse]:
    """Build a `FunctionModel` function that always returns `document_type`
    as `classification_agent`'s structured output. Shared with
    `tests/services/test_document.py`'s upload-classification tests so both
    modules build the stub the same way."""

    def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args={"response": document_type.value})]
        )

    return _fn


@pytest.fixture(autouse=True)
def _stub_document_classification() -> Iterator[None]:
    """Default every test's `upload_document` calls to a stubbed, no-network
    classification (`DocumentType.OTHER`) so the suite never depends on a
    real Anthropic call. Tests that care about classification specifically
    (see `tests/services/test_llm.py` and
    `tests/services/test_document.py`'s upload-classification tests) layer
    their own `classification_agent.override(...)` inside the test body,
    which -- as an inner context manager -- takes precedence over this outer
    default.
    """
    with classification_agent.override(
        model=FunctionModel(make_classification_stub(DocumentType.OTHER))
    ):
        yield


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
    # `send_message`'s streamed response opens a *second* session later (via
    # `get_session_factory`, see that dependency's docstring) that isn't
    # reachable through the `get_session` override above -- it must be
    # pointed at the isolated test database too, or it silently talks to
    # whatever engine `takehome.db.session` was first imported with, which
    # can corrupt state across the schema resets `_reset_database` does
    # between tests.
    app.dependency_overrides[get_session_factory] = lambda: TestSessionLocal

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_session_factory, None)
