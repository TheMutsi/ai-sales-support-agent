"""Shared fixtures for RAG integration tests (`test_rag_ingestion.py`,
`test_retriever.py`) — both need a Postgres session with `Document`/
`DocumentChunk` wiped before and after each test.
"""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk
from app.db.session import SessionLocal


def _wipe(session: Session) -> None:
    session.query(DocumentChunk).delete()
    session.query(Document).delete()
    session.commit()


@pytest.fixture
def rag_db() -> Session:
    session = SessionLocal()
    _wipe(session)
    try:
        yield session
    finally:
        # The functions under test (ingest(), _add_document() helpers) commit
        # internally, so a plain rollback() here wouldn't undo anything — clean
        # up explicitly instead of leaving synthetic test rows in what's
        # otherwise the developer's real KB data.
        _wipe(session)
        session.close()
