from datetime import datetime
from typing import TypedDict, cast
from uuid import UUID

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from ecommerce_store_qa.domain.session import Exchange, ExchangeSource, Operation, Session


class SessionDocument(TypedDict):
    _id: str
    operation: str
    jira_issue_key: str | None
    snapshot_id: str | None
    created_at: datetime


class ExchangeDocument(TypedDict):
    _id: str
    exchange_id: str
    session_id: str
    source: str
    request_json: str
    response_json: str
    model: str | None
    created_at: datetime


type Document = SessionDocument | ExchangeDocument


class MongoSessionRepository:
    def __init__(self, database: AsyncDatabase[Document]) -> None:
        self._sessions = cast(AsyncCollection[SessionDocument], database.get_collection("sessions"))
        self._exchanges = cast(AsyncCollection[ExchangeDocument], database.get_collection("exchanges"))

    async def add_session(self, session: Session) -> None:
        await self._sessions.insert_one(
            SessionDocument(
                _id=str(session.id),
                operation=session.operation.value,
                jira_issue_key=session.jira_issue_key,
                snapshot_id=session.snapshot_id,
                created_at=session.created_at,
            )
        )

    async def get_session(self, session_id: UUID) -> Session | None:
        document = await self._sessions.find_one({"_id": str(session_id)})
        if document is None:
            return None
        return Session(
            UUID(document["_id"]),
            Operation(document["operation"]),
            document["jira_issue_key"],
            document["snapshot_id"],
            document["created_at"],
        )

    async def store_exchange(self, exchange: Exchange) -> Exchange:
        try:
            await self._exchanges.insert_one(
                ExchangeDocument(
                    _id=_key(exchange.session_id, exchange.id),
                    exchange_id=str(exchange.id),
                    session_id=str(exchange.session_id),
                    source=exchange.source.value,
                    request_json=exchange.request_json,
                    response_json=exchange.response_json,
                    model=exchange.model,
                    created_at=exchange.created_at,
                )
            )
        except DuplicateKeyError:
            existing = await self.get_exchange(exchange.session_id, exchange.id)
            if existing is None:
                raise
            return existing
        return exchange

    async def get_exchange(self, session_id: UUID, exchange_id: UUID) -> Exchange | None:
        document = await self._exchanges.find_one({"_id": _key(session_id, exchange_id)})
        if document is None:
            return None
        return Exchange(
            UUID(document["exchange_id"]),
            UUID(document["session_id"]),
            ExchangeSource(document["source"]),
            document["request_json"],
            document["response_json"],
            document["model"],
            document["created_at"],
        )


def _key(session_id: UUID, exchange_id: UUID) -> str:
    return f"{session_id}:{exchange_id}"
