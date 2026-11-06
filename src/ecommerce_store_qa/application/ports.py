from typing import Protocol
from uuid import UUID

from ecommerce_store_qa.domain.session import Exchange, Session


class SessionRepository(Protocol):
    async def add_session(self, session: Session) -> None: ...
    async def get_session(self, session_id: UUID) -> Session | None: ...
    async def get_exchange(self, session_id: UUID, exchange_id: UUID) -> Exchange | None: ...

    async def store_exchange(self, exchange: Exchange) -> Exchange:
        """Insert once and return the persisted record, including on a duplicate ID."""
        ...
