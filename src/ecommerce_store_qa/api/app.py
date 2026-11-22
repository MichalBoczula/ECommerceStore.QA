from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from hmac import compare_digest
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Security
from fastapi.security import APIKeyHeader
from httpx2 import AsyncBaseTransport, AsyncClient
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from starlette.requests import Request

from ecommerce_store_qa.api.contracts import (
    CaptureExchangeRequest,
    CreateSessionRequest,
    ExchangeResponse,
    SessionResponse,
)
from ecommerce_store_qa.api.errors import (
    BAD_REQUEST,
    PROBLEM_MEDIA_TYPE,
    UNAUTHORIZED,
    UNAVAILABLE,
    RequestProblem,
    install_error_handlers,
    problem_responses,
)
from ecommerce_store_qa.application.e2e_models import AuthorRequest, E2EProposal, E2EPullRequest, PublishRequest
from ecommerce_store_qa.application.e2e_service import E2EService
from ecommerce_store_qa.application.ports import SessionRepository
from ecommerce_store_qa.application.session_service import CaptureExchange, SessionService, canonical_json
from ecommerce_store_qa.infrastructure.ba_handoff import BaHandoffClient
from ecommerce_store_qa.infrastructure.github_e2e import GitHubFeaturePublisher
from ecommerce_store_qa.infrastructure.mongo_repository import Document, MongoSessionRepository
from ecommerce_store_qa.infrastructure.settings import Settings

key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


def create_app(
    settings: Settings | None = None,
    repository: SessionRepository | None = None,
    *,
    ba_transport: AsyncBaseTransport | None = None,
    github_transport: AsyncBaseTransport | None = None,
) -> FastAPI:
    config = settings or Settings()
    expected_key = config.api_key.get_secret_value().encode()
    if not expected_key:
        raise ValueError("QA_API_KEY must be configured")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            store = repository
            if store is None:
                client = await stack.enter_async_context(
                    AsyncMongoClient[Document](
                        config.mongodb_uri.get_secret_value(),
                        tz_aware=True,
                        timeoutMS=3000,
                    )
                )
                app.state.mongo = client
                store = MongoSessionRepository(client[config.mongodb_database])
            sessions = SessionService(store)
            app.state.session_service = sessions
            handoffs = None
            if config.ba_api_url is not None and config.ba_api_key.get_secret_value():
                ba = await stack.enter_async_context(
                    AsyncClient(
                        base_url=str(config.ba_api_url).rstrip("/") + "/",
                        headers={"X-Api-Key": config.ba_api_key.get_secret_value()},
                        timeout=25,
                        follow_redirects=False,
                        transport=ba_transport,
                    )
                )
                handoffs = BaHandoffClient(ba)
            publisher = None
            if token := config.e2e_github_token.get_secret_value():
                github = await stack.enter_async_context(
                    AsyncClient(
                        base_url="https://api.github.com/",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                        timeout=25,
                        follow_redirects=False,
                        transport=github_transport,
                    )
                )
                publisher = GitHubFeaturePublisher(github)
            app.state.e2e_service = E2EService(sessions, handoffs, publisher)
            yield

    app = FastAPI(title="ECommerce Store QA", docs_url="/swagger", lifespan=lifespan)
    install_error_handlers(app)

    async def authorize(key: Annotated[str | None, Security(key_header)]) -> None:
        if key is None or not compare_digest(expected_key, key.encode()):
            raise RequestProblem(UNAUTHORIZED)

    def session_service(request: Request) -> SessionService:
        return cast(SessionService, request.app.state.session_service)

    def e2e_service(request: Request) -> E2EService:
        return cast(E2EService, request.app.state.e2e_service)

    router = APIRouter(prefix="/api/v1/sessions", tags=["Sessions"], dependencies=[Depends(authorize)])

    @app.get("/health/live", tags=["Health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"], responses=problem_responses(503))
    async def ready(request: Request) -> dict[str, str]:
        if repository is None:
            client = cast(AsyncMongoClient[Document], request.app.state.mongo)
            try:
                await client.admin.command("ping")
            except PyMongoError as error:
                raise RequestProblem(UNAVAILABLE) from error
        return {"status": "ok"}

    @router.post("", status_code=201, responses=problem_responses(400, 401, 503))
    async def create_session(
        body: CreateSessionRequest, service: Annotated[SessionService, Depends(session_service)]
    ) -> SessionResponse:
        return SessionResponse.from_domain(await service.create(body.operation, body.jira_issue_key, body.snapshot_id))

    @router.get("/{session_id}", responses=problem_responses(400, 401, 404, 503))
    async def get_session(
        session_id: UUID, service: Annotated[SessionService, Depends(session_service)]
    ) -> SessionResponse:
        return SessionResponse.from_domain(await service.get(session_id))

    @router.put("/{session_id}/exchanges/{exchange_id}", responses=problem_responses(400, 401, 404, 409, 413, 503))
    async def capture_exchange(
        session_id: UUID,
        exchange_id: UUID,
        body: CaptureExchangeRequest,
        service: Annotated[SessionService, Depends(session_service)],
    ) -> ExchangeResponse:
        try:
            request_json = canonical_json(body.request)
            response_json = canonical_json(body.response)
        except (ValueError, RecursionError) as error:
            raise RequestProblem(BAD_REQUEST) from error
        capture = CaptureExchange(body.source, request_json, response_json, body.model)
        return ExchangeResponse.from_domain(await service.capture(session_id, exchange_id, capture))

    @router.get("/{session_id}/exchanges/{exchange_id}", responses=problem_responses(400, 401, 404, 503))
    async def get_exchange(
        session_id: UUID, exchange_id: UUID, service: Annotated[SessionService, Depends(session_service)]
    ) -> ExchangeResponse:
        return ExchangeResponse.from_domain(await service.get_exchange(session_id, exchange_id))

    @router.put("/{session_id}/e2e-proposals/{proposal_id}", responses=problem_responses(400, 401, 404, 409, 413, 503))
    async def author_e2e(
        session_id: UUID,
        proposal_id: UUID,
        body: AuthorRequest,
        service: Annotated[E2EService, Depends(e2e_service)],
    ) -> E2EProposal:
        return await service.author(session_id, proposal_id, body)

    @router.put(
        "/{session_id}/e2e-proposals/{proposal_id}/pull-request", responses=problem_responses(400, 401, 404, 409, 503)
    )
    async def publish_e2e(
        session_id: UUID,
        proposal_id: UUID,
        body: PublishRequest,
        service: Annotated[E2EService, Depends(e2e_service)],
    ) -> E2EPullRequest:
        return await service.publish(session_id, proposal_id, body.feature_sha256)

    app.include_router(router)
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original_openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                responses = operation["responses"]
                responses.pop("422", None)
                for status, response in responses.items():
                    if int(status) >= 400 and "application/json" in response.get("content", {}):
                        content = response["content"]
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
        return schema

    app.openapi = openapi
    return app
