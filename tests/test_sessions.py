from base64 import b64decode, b64encode
from json import loads
from os import getenv
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import MockTransport, ReadTimeout, Request, Response
from pydantic import AnyHttpUrl, SecretStr
from pymongo import MongoClient

from ecommerce_store_qa.api.app import create_app
from ecommerce_store_qa.application.e2e_models import E2E_REPOSITORY, FEATURE_PATH, MANAGED_FEATURE
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


def test_author_and_publish_e2e_from_published_ba_handoff() -> None:
    ba_session, ba_run = str(uuid4()), str(uuid4())
    source_id = "products-openapi"
    published_at = "2026-11-22T10:00:00Z"
    draft = {
        "snapshotId": "snapshot-1",
        "evidenceExchangeId": str(uuid4()),
        "process": {
            "acceptanceCriteria": [
                {
                    "title": "Open a smartphone from the catalog",
                    "given": "The catalog lists an active smartphone",
                    "when": "A customer opens its details",
                    "then": "The details show that smartphone and its specifications",
                    "sourceIds": [source_id],
                }
            ]
        },
        "sources": [
            {
                "id": source_id,
                "snapshotId": "snapshot-1",
                "service": "products",
                "path": "sources/openapi.json#/paths/~1mobile-phones/get",
                "commitSha": "a" * 40,
            }
        ],
    }
    ba_state = {"status": "draft", "method": "GET"}
    ba_reads: list[str] = []

    def ba(request: Request) -> Response:
        assert request.headers["x-api-key"] == "test-ba-key"
        assert "authorization" not in request.headers
        assert request.method == "GET"
        assert request.url.path == f"/api/v1/sessions/{ba_session}/runs/{ba_run}/handoff"
        ba_reads.append(request.url.path)
        return Response(
            200,
            json={
                "id": ba_run,
                "sessionId": ba_session,
                "status": ba_state["status"],
                "approvedAt": published_at,
                "publishedAt": published_at,
                "draftSha256": "b" * 64,
                "request": {"service": "products", "method": ba_state["method"], "path": "/mobile-phones"},
                "draft": draft,
                "jiraIssue": {"key": "STORE-12"},
            },
        )

    repo_api = f"/repos/{E2E_REPOSITORY}"
    main_sha = "c" * 40
    blob_sha = "d" * 40
    github_writes: list[str] = []
    pulls: list[dict[str, object]] = []
    updated_features: list[str] = []

    def github(request: Request) -> Response:
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == "Bearer test-github-token"
        assert "x-api-key" not in request.headers
        method, path = request.method, request.url.path
        if method == "GET":
            if path == f"{repo_api}/pulls":
                assert request.url.params["base"] == "main"
                return Response(200, json=pulls)
            if path == f"{repo_api}/git/ref/heads/main":
                return Response(200, json={"object": {"sha": main_sha}})
            assert path == f"{repo_api}/contents/{FEATURE_PATH}"
            initial = b64encode((MANAGED_FEATURE + "\nFeature: Starter\n").encode()).decode()
            return Response(200, json={"sha": blob_sha, "encoding": "base64", "content": initial})

        github_writes.append(f"{method} {path}")
        payload = loads(request.content)
        if path == f"{repo_api}/git/refs":
            assert method == "POST" and payload["sha"] == main_sha
            assert payload["ref"].startswith("refs/heads/qa/catalog-phone-details-")
            return Response(201)
        if path == f"{repo_api}/contents/{FEATURE_PATH}":
            assert method == "PUT" and payload["sha"] == blob_sha
            updated_features.append(b64decode(payload["content"]).decode())
            return Response(200)
        assert method == "POST" and path == f"{repo_api}/pulls"
        assert payload["base"] == "main"
        assert "qa-feature-sha256:" in payload["body"]
        pulls.append({"number": 42, "head": {"ref": payload["head"]}, "body": payload["body"]})
        raise ReadTimeout("The pull request was created before the response timed out", request=request)

    app = create_app(
        Settings(
            api_key=SecretStr("test-only-key"),
            ba_api_url=AnyHttpUrl("https://ba.example/"),
            ba_api_key=SecretStr("test-ba-key"),
            e2e_github_token=SecretStr("test-github-token"),
        ),
        MemoryRepository(),
        ba_transport=MockTransport(ba),
        github_transport=MockTransport(github),
    )
    headers = {"X-Api-Key": "test-only-key"}
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/sessions",
            json={"operation": "author", "jiraIssueKey": "STORE-12", "snapshotId": "snapshot-1"},
            headers=headers,
        )
        assert created.status_code == 201
        url = f"/api/v1/sessions/{created.json()['id']}/e2e-proposals/{uuid4()}"
        selection = {"baSessionId": ba_session, "baRunId": ba_run, "criterionIndex": 0}
        unapproved = client.put(url, json=selection, headers=headers)
        assert unapproved.status_code == 409
        assert unapproved.json()["code"] == "ba_handoff_required"

        ba_state.update(status="published", method="POST")
        wrong_operation = client.put(url, json=selection, headers=headers)
        assert wrong_operation.status_code == 409
        assert wrong_operation.json()["code"] == "unsupported_e2e_proposal"

        ba_state["method"] = "GET"
        authored = client.put(url, json=selection, headers=headers)
        assert authored.status_code == 200, authored.text
        proposal = authored.json()
        assert proposal["path"] == FEATURE_PATH
        assert proposal["provenance"]["baRunId"] == ba_run
        assert proposal["provenance"]["criterion"]["sourceIds"] == [source_id]
        assert "When I open a listed smartphone" in proposal["feature"]
        assert client.put(url, json=selection, headers=headers).json() == proposal
        assert len(ba_reads) == 3
        assert not github_writes

        publish_url = f"{url}/pull-request"
        stale = client.put(publish_url, json={"featureSha256": "0" * 64}, headers=headers)
        assert stale.status_code == 409
        assert not github_writes

        review = {"featureSha256": proposal["featureSha256"]}
        assert client.put(publish_url, json=review, headers=headers).status_code == 503
        receipt = client.put(publish_url, json=review, headers=headers)
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["url"] == f"https://github.com/{E2E_REPOSITORY}/pull/42"
        assert client.put(publish_url, json=review, headers=headers).json() == receipt.json()

    assert len(ba_reads) == 5
    assert github_writes == [
        f"POST {repo_api}/git/refs",
        f"PUT {repo_api}/contents/{FEATURE_PATH}",
        f"POST {repo_api}/pulls",
    ]
    assert updated_features == [proposal["feature"]]


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
