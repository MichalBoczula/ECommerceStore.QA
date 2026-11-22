from datetime import datetime
from hashlib import sha256
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

E2E_REPOSITORY = "MichalBoczula/ECommerceStore.E2E"
FEATURE_PATH = "features/catalog/browse-phone-details.feature"
MANAGED_FEATURE = "# Managed by ECommerceStore.QA. Journey catalog-phone-details v1."


class BaHandoffError(Exception):
    pass


class UnsupportedProposalError(Exception):
    pass


class E2EUnavailableError(Exception):
    pass


class E2EPublicationConflictError(Exception):
    pass


class E2EModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)


class AuthorRequest(E2EModel):
    model_config = ConfigDict(extra="forbid")

    ba_session_id: UUID
    ba_run_id: UUID
    criterion_index: int = Field(ge=0, strict=True)


class PublishRequest(E2EModel):
    model_config = ConfigDict(extra="forbid")

    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Criterion(E2EModel):
    title: str
    given: str
    when: str
    then: str
    source_ids: list[str]


class Process(E2EModel):
    acceptance_criteria: list[Criterion]


class Source(E2EModel):
    id: str
    snapshot_id: str
    service: str
    path: str
    commit_sha: str


class JiraIssue(E2EModel):
    key: str


class BaDraft(E2EModel):
    snapshot_id: str
    evidence_exchange_id: UUID
    process: Process
    sources: list[Source]
    jira_context: JiraIssue | None = None


class Operation(E2EModel):
    service: str
    method: str
    path: str


class BaHandoff(E2EModel):
    id: UUID
    session_id: UUID
    status: Literal["published"]
    approved_at: datetime
    published_at: datetime
    draft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: Operation
    draft: BaDraft
    jira_issue: JiraIssue


class Provenance(E2EModel):
    ba_session_id: UUID
    ba_run_id: UUID
    snapshot_id: str
    draft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_exchange_id: UUID
    jira_issue_key: str
    criterion_index: int = Field(ge=0, strict=True)
    criterion: Criterion
    sources: list[Source]


class E2EProposal(E2EModel):
    provenance: Provenance
    path: Literal["features/catalog/browse-phone-details.feature"] = FEATURE_PATH
    feature: str
    feature_sha256: str


class E2EPullRequest(E2EModel):
    repository: str = E2E_REPOSITORY
    branch: str | None = None
    status: Literal["pull_request", "already_current"]
    url: str
    number: int | None = None


class HandoffReader(Protocol):
    async def read(self, session_id: UUID, run_id: UUID) -> BaHandoff: ...


class FeaturePublisher(Protocol):
    async def publish(self, proposal: E2EProposal) -> E2EPullRequest: ...


def render_feature(source: Provenance) -> str:
    return (
        f"{MANAGED_FEATURE}\n"
        f"# BA session {source.ba_session_id}\n"
        f"# BA run {source.ba_run_id}\n"
        f"# BA acceptanceCriteria[{source.criterion_index}]\n"
        f"# BA draft SHA-256 {source.draft_sha256}\n"
        f"# Knowledge snapshot {' '.join(source.snapshot_id.split())}\n"
        "@catalog @smoke\n"
        "Feature: Browse smartphone details\n\n"
        "  Scenario: Open a listed smartphone and verify its details\n"
        "    Given the smartphone catalog is open\n"
        "    When I open a listed smartphone\n"
        "    Then the details match the selected smartphone\n"
        "    And I can see its specifications\n"
    )


def feature_sha256(feature: str) -> str:
    return sha256(feature.encode("utf-8")).hexdigest()
