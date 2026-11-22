from re import fullmatch
from uuid import UUID, uuid5

from pydantic import ValidationError

from ecommerce_store_qa.application.e2e_models import (
    AuthorRequest,
    BaHandoff,
    BaHandoffError,
    E2EProposal,
    E2EPullRequest,
    E2EUnavailableError,
    FeaturePublisher,
    HandoffReader,
    Provenance,
    UnsupportedProposalError,
    feature_sha256,
    render_feature,
)
from ecommerce_store_qa.application.session_service import (
    CaptureExchange,
    ExchangeConflictError,
    ExchangeNotFoundError,
    SessionService,
    canonical_json,
)
from ecommerce_store_qa.domain.session import Exchange, ExchangeSource, Operation, Session


class E2EService:
    def __init__(
        self, sessions: SessionService, handoffs: HandoffReader | None, publisher: FeaturePublisher | None
    ) -> None:
        self._sessions = sessions
        self._handoffs = handoffs
        self._publisher = publisher

    async def author(self, session_id: UUID, proposal_id: UUID, body: AuthorRequest) -> E2EProposal:
        session = await self._author_session(session_id)
        request_json = canonical_json({"kind": "e2e-proposal", "input": body.model_dump(mode="json", by_alias=True)})
        existing = await self._find_exchange(session_id, proposal_id, request_json)
        if existing is not None:
            return _proposal(existing)
        if self._handoffs is None:
            raise E2EUnavailableError
        handoff = await self._handoffs.read(body.ba_session_id, body.ba_run_id)
        provenance = _select_provenance(session, handoff, body)
        feature = render_feature(provenance)
        draft = E2EProposal(provenance=provenance, feature=feature, feature_sha256=feature_sha256(feature))
        exchange = await self._sessions.capture(
            session_id,
            proposal_id,
            CaptureExchange(ExchangeSource.AGENT, request_json, draft.model_dump_json(by_alias=True), None),
        )
        return _proposal(exchange)

    async def publish(self, session_id: UUID, proposal_id: UUID, expected_sha256: str) -> E2EPullRequest:
        session = await self._author_session(session_id)
        proposal = _proposal(await self._sessions.get_exchange(session_id, proposal_id))
        if proposal.feature_sha256 != expected_sha256:
            raise ExchangeConflictError

        receipt_id = uuid5(proposal_id, "e2e-pull-request")
        request_json = canonical_json(
            {"kind": "e2e-pull-request", "proposalId": str(proposal_id), "sha256": expected_sha256}
        )
        existing = await self._find_exchange(session_id, receipt_id, request_json)
        if existing is not None:
            return E2EPullRequest.model_validate_json(existing.response_json)
        if self._publisher is None or self._handoffs is None:
            raise E2EUnavailableError
        source = proposal.provenance
        original = AuthorRequest(
            ba_session_id=source.ba_session_id, ba_run_id=source.ba_run_id, criterion_index=source.criterion_index
        )
        handoff = await self._handoffs.read(original.ba_session_id, original.ba_run_id)
        if _select_provenance(session, handoff, original) != source:
            raise ExchangeConflictError
        result = await self._publisher.publish(proposal)
        exchange = await self._sessions.capture(
            session_id,
            receipt_id,
            CaptureExchange(ExchangeSource.AGENT, request_json, result.model_dump_json(by_alias=True), None),
        )
        return E2EPullRequest.model_validate_json(exchange.response_json)

    async def _author_session(self, session_id: UUID) -> Session:
        session = await self._sessions.get(session_id)
        if session.operation != Operation.AUTHOR:
            raise UnsupportedProposalError
        return session

    async def _find_exchange(self, session_id: UUID, exchange_id: UUID, request_json: str) -> Exchange | None:
        try:
            exchange = await self._sessions.get_exchange(session_id, exchange_id)
        except ExchangeNotFoundError:
            return None
        if exchange.source != ExchangeSource.AGENT or exchange.request_json != request_json:
            raise ExchangeConflictError
        return exchange


def _proposal(exchange: Exchange) -> E2EProposal:
    try:
        proposal = E2EProposal.model_validate_json(exchange.response_json)
    except ValidationError:
        raise ExchangeConflictError from None
    if (
        exchange.source != ExchangeSource.AGENT
        or proposal.feature != render_feature(proposal.provenance)
        or proposal.feature_sha256 != feature_sha256(proposal.feature)
    ):
        raise ExchangeConflictError
    return proposal


def _select_provenance(session: Session, handoff: BaHandoff, body: AuthorRequest) -> Provenance:
    if (handoff.session_id, handoff.id) != (body.ba_session_id, body.ba_run_id):
        raise BaHandoffError
    draft = handoff.draft
    operation = handoff.request
    if (
        operation.service != "products"
        or operation.method != "GET"
        or (operation.path != "/mobile-phones" and not fullmatch(r"/mobile-phones/\{[a-zA-Z0-9_]+\}", operation.path))
        or session.snapshot_id not in (None, draft.snapshot_id)
        or session.jira_issue_key not in (None, handoff.jira_issue.key)
        or body.criterion_index >= len(draft.process.acceptance_criteria)
    ):
        raise UnsupportedProposalError
    source_ids = {source.id for source in draft.sources}
    if draft.jira_context is not None:
        source_ids.add(f"jira:{draft.jira_context.key}")
    criterion = draft.process.acceptance_criteria[body.criterion_index]
    if (
        not criterion.source_ids
        or not all(text.strip() for text in (criterion.title, criterion.given, criterion.when, criterion.then))
        or not set(criterion.source_ids) <= source_ids
        or any(
            (source.service, source.snapshot_id) != (operation.service, draft.snapshot_id) for source in draft.sources
        )
        or not any(source.path.startswith("sources/openapi.json#/") for source in draft.sources)
    ):
        raise BaHandoffError
    return Provenance(
        ba_session_id=handoff.session_id,
        ba_run_id=handoff.id,
        snapshot_id=draft.snapshot_id,
        draft_sha256=handoff.draft_sha256,
        evidence_exchange_id=draft.evidence_exchange_id,
        jira_issue_key=handoff.jira_issue.key,
        criterion_index=body.criterion_index,
        criterion=criterion,
        sources=draft.sources,
    )
