from os import getenv
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pymongo import MongoClient

from ecommerce_store_qa.api.app import create_app
from ecommerce_store_qa.domain.session import Exchange, Session
from ecommerce_store_qa.infrastructure.settings import Settings


class MemoryRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, Session] = {}
        self.exchanges: dict[tuple[UUID, UUID], Exchange] = {}

    async def add_session(self, session: Session) -> None:
        self.sessions[session.id] = session

    async def get_session(self, session_id: UUID) -> Session | None:
        return self.sessions.get(session_id)

    async def get_exchange(self, session_id: UUID, exchange_id: UUID) -> Exchange | None:
        return self.exchanges.get((session_id, exchange_id))

    async def store_exchange(self, exchange: Exchange) -> Exchange:
        return self.exchanges.setdefault((exchange.session_id, exchange.id), exchange)


def _exercise_session(client: TestClient) -> tuple[str, str, dict[str, str]]:
    headers = {"X-Api-Key": "test-only-key"}
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.post("/api/v1/sessions", json={"operation": "author"}).status_code == 401
    invalid = client.post("/api/v1/sessions", json={"operation": "invalid"}, headers=headers)
    assert invalid.status_code == 400
    assert invalid.headers["content-type"] == "application/problem+json"
    assert invalid.json()["traceId"] == invalid.headers["x-trace-id"]
    created = client.post(
        "/api/v1/sessions",
        json={"operation": "author", "jiraIssueKey": "STORE-12", "snapshotId": "snapshot-1"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    session_url = f"/api/v1/sessions/{created.json()['id']}"
    assert client.get(session_url, headers=headers).json() == created.json()
    exchange_url = f"{session_url}/exchanges/{uuid4()}"
    assert client.get(exchange_url, headers=headers).status_code == 404
    capture = {
        "source": "agent",
        "request": {"$key.with.dots": "test prompt", "context": ["doc-1"]},
        "response": {"answer": "test answer"},
        "model": "synthetic-test-model",
    }
    recorded = client.put(exchange_url, json=capture, headers=headers)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["request"] == capture["request"]
    assert recorded.json()["response"] == capture["response"]
    assert client.put(exchange_url, json=capture, headers=headers).json() == recorded.json()
    changed = client.put(exchange_url, json={**capture, "response": {"answer": "changed"}}, headers=headers)
    assert changed.status_code == 409
    assert client.get(exchange_url, headers=headers).json() == recorded.json()
    oversized = client.put(
        f"{session_url}/exchanges/{uuid4()}",
        json={**capture, "response": "x" * (256 * 1024)},
        headers=headers,
    )
    assert oversized.status_code == 413
    unknown_session_url = f"/api/v1/sessions/{uuid4()}/exchanges/{uuid4()}"
    assert client.put(unknown_session_url, json=capture, headers=headers).status_code == 404
    return session_url, exchange_url, headers


def test_session_and_immutable_capture() -> None:
    app = create_app(Settings(api_key=SecretStr("test-only-key")), MemoryRepository())
    with TestClient(app) as client:
        _exercise_session(client)
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/api/v1/sessions"]["post"]
        assert "422" not in operation["responses"]
        assert operation["responses"]["400"]["content"]["application/problem+json"]["schema"] == {
            "$ref": "#/components/schemas/ProblemDetails"
        }
        assert operation["security"]


@pytest.mark.skipif(not getenv("TEST_MONGODB_URI"), reason="Set TEST_MONGODB_URI to run real MongoDB checks")
def test_mongodb_persists_capture_across_restarts() -> None:
    uri = getenv("TEST_MONGODB_URI", "")
    database = f"test_qa_{uuid4().hex}"
    settings = Settings(api_key=SecretStr("test-only-key"), mongodb_uri=SecretStr(uri), mongodb_database=database)
    try:
        with TestClient(create_app(settings)) as client:
            session_url, exchange_url, headers = _exercise_session(client)
            captured = client.get(exchange_url, headers=headers).json()
        with TestClient(create_app(settings)) as client:
            assert client.get(session_url, headers=headers).json()["jiraIssueKey"] == "STORE-12"
            assert client.get(exchange_url, headers=headers).json() == captured
    finally:
        with MongoClient[dict[str, object]](uri, timeoutMS=3000) as mongo:
            mongo.drop_database(database)
