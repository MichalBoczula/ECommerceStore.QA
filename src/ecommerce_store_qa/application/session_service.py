from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ecommerce_store_qa.application.ports import SessionRepository
from ecommerce_store_qa.domain.session import Exchange, ExchangeSource, Operation, Session

MAX_EXCHANGE_BYTES = 256 * 1024


class SessionNotFoundError(Exception):
    pass


class ExchangeNotFoundError(Exception):
    pass


class ExchangeConflictError(Exception):
    pass


class ExchangeTooLargeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CaptureExchange:
    source: ExchangeSource
    request_json: str
    response_json: str
    model: str | None


class SessionService:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def create(self, operation: Operation, jira_issue_key: str | None, snapshot_id: str | None) -> Session:
        session = Session(uuid4(), operation, jira_issue_key, snapshot_id, _utc_now())
        await self._repository.add_session(session)
        return session

    async def get(self, session_id: UUID) -> Session:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise SessionNotFoundError
        return session

    async def capture(self, session_id: UUID, exchange_id: UUID, data: CaptureExchange) -> Exchange:
        size = len(data.request_json.encode("utf-8")) + len(data.response_json.encode("utf-8"))
        if size > MAX_EXCHANGE_BYTES:
            raise ExchangeTooLargeError
        await self.get(session_id)
        exchange = Exchange(
            exchange_id, session_id, data.source, data.request_json, data.response_json, data.model, _utc_now()
        )
        persisted = await self._repository.store_exchange(exchange)
        if not persisted.same_payload(exchange):
            raise ExchangeConflictError
        return persisted

    async def get_exchange(self, session_id: UUID, exchange_id: UUID) -> Exchange:
        await self.get(session_id)
        exchange = await self._repository.get_exchange(session_id, exchange_id)
        if exchange is None:
            raise ExchangeNotFoundError
        return exchange


def _utc_now() -> datetime:
    now = datetime.now(UTC)
    # MongoDB stores BSON datetimes at millisecond precision.
    return now.replace(microsecond=now.microsecond // 1000 * 1000)
