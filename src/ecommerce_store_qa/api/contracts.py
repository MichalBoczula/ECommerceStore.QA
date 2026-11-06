from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter
from pydantic.alias_generators import to_camel

from ecommerce_store_qa.domain.session import Exchange, ExchangeSource, Operation, Session

JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", validate_by_name=True)


class CreateSessionRequest(ApiModel):
    operation: Operation
    jira_issue_key: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*-[0-9]+$")
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=256)


class SessionResponse(ApiModel):
    id: UUID
    operation: Operation
    jira_issue_key: str | None
    snapshot_id: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, session: Session) -> SessionResponse:
        return cls(
            id=session.id,
            operation=session.operation,
            jira_issue_key=session.jira_issue_key,
            snapshot_id=session.snapshot_id,
            created_at=session.created_at,
        )


class CaptureExchangeRequest(ApiModel):
    source: ExchangeSource
    request: JsonValue
    response: JsonValue
    model: str | None = Field(default=None, min_length=1, max_length=128)


class ExchangeResponse(ApiModel):
    id: UUID
    session_id: UUID
    source: ExchangeSource
    request: JsonValue
    response: JsonValue
    model: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, exchange: Exchange) -> ExchangeResponse:
        return cls(
            id=exchange.id,
            session_id=exchange.session_id,
            source=exchange.source,
            request=JSON_VALUE.validate_json(exchange.request_json),
            response=JSON_VALUE.validate_json(exchange.response_json),
            model=exchange.model,
            created_at=exchange.created_at,
        )
