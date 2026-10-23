import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def make_client(tmp_path):
    """Build a TestClient backed by a throwaway SQLite file."""
    clients = []

    def factory(rate_limit: int = 1000) -> TestClient:
        app = create_app(db_path=str(tmp_path / "test.db"), rate_limit=rate_limit)
        client = TestClient(app, follow_redirects=False)
        client.__enter__()  # runs the lifespan, which creates the schema
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()
