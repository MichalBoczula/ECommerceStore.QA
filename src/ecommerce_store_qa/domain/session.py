from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Operation(StrEnum):
    AUTHOR = "author"
    EXECUTE = "execute"


class ExchangeSource(StrEnum):
    AGENT = "agent"
    JIRA = "jira"
    RAG = "rag"


@dataclass(frozen=True, slots=True)
class Session:
    id: UUID
    operation: Operation
    jira_issue_key: str | None
    snapshot_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Exchange:
    id: UUID
    session_id: UUID
    source: ExchangeSource
    request_json: str
    response_json: str
    model: str | None
    created_at: datetime

    def same_payload(self, other: Exchange) -> bool:
        return (
            self.source,
            self.request_json,
            self.response_json,
            self.model,
        ) == (
            other.source,
            other.request_json,
            other.response_json,
            other.model,
        )
