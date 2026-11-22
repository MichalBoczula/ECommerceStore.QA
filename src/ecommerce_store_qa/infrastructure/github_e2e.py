from base64 import b64decode, b64encode
from binascii import Error as Base64Error

from httpx2 import AsyncClient, RequestError, Response
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from ecommerce_store_qa.application.e2e_models import (
    E2E_REPOSITORY,
    FEATURE_PATH,
    MANAGED_FEATURE,
    E2EProposal,
    E2EPublicationConflictError,
    E2EPullRequest,
    E2EUnavailableError,
)

BASE_BRANCH = "main"
REPO_API = f"repos/{E2E_REPOSITORY}"


class _GitObject(BaseModel):
    sha: str


class _Ref(BaseModel):
    object: _GitObject


class _File(BaseModel):
    sha: str
    encoding: str
    content: str

    def read(self) -> bytes:
        if self.encoding != "base64":
            raise E2EUnavailableError
        try:
            return b64decode("".join(self.content.split()), validate=True)
        except Base64Error:
            raise E2EUnavailableError from None


class _PullHead(BaseModel):
    ref: str


class _Pull(BaseModel):
    number: int = Field(gt=0)
    body: str | None = None
    head: _PullHead


_PULLS = TypeAdapter(list[_Pull])


class GitHubFeaturePublisher:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def publish(self, proposal: E2EProposal) -> E2EPullRequest:
        branch = f"qa/catalog-phone-details-{proposal.feature_sha256[:24]}"
        marker = f"<!-- qa-feature-sha256: {proposal.feature_sha256} -->"
        existing = await self._find_pull(branch, marker)
        if existing is not None:
            return _receipt(existing)

        base = await self._ref(BASE_BRANCH)
        base_file = await self._feature_at(base.object.sha)
        base_content = base_file.read()
        if not base_content.startswith((MANAGED_FEATURE + "\n").encode()):
            raise E2EPublicationConflictError
        desired = proposal.feature.encode("utf-8")
        if base_content == desired:
            return E2EPullRequest(
                status="already_current", url=f"https://github.com/{E2E_REPOSITORY}/blob/{BASE_BRANCH}/{FEATURE_PATH}"
            )

        created = await self._request(
            "POST", f"{REPO_API}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base.object.sha}
        )
        if created.status_code != 201:
            if created.status_code != 422:
                raise E2EUnavailableError
            await self._ref(branch)

        current = await self._feature_at(branch)
        if current.read() != desired:
            if current.sha != base_file.sha:
                raise E2EPublicationConflictError
            updated = await self._request(
                "PUT",
                f"{REPO_API}/contents/{FEATURE_PATH}",
                json={
                    "message": "Bind catalog details smoke to the approved BA handoff",
                    "content": b64encode(desired).decode("ascii"),
                    "branch": branch,
                    "sha": current.sha,
                },
            )
            if updated.status_code != 200:
                if updated.status_code not in {409, 422}:
                    raise E2EUnavailableError
                if (await self._feature_at(branch)).read() != desired:
                    raise E2EPublicationConflictError

        source = proposal.provenance
        body = (
            "Exercise the catalog to smartphone details journey using the checked-in Playwright steps.\n\n"
            f"BA run `{source.ba_run_id}`\n"
            f"\nAcceptance criterion `acceptanceCriteria[{source.criterion_index}]`\n"
            f"\nKnowledge snapshot `{' '.join(source.snapshot_id.split())}`\n"
            f"\nDraft SHA-256 `{source.draft_sha256}`\n\n{marker}\n"
        )
        response = await self._request(
            "POST",
            f"{REPO_API}/pulls",
            json={"title": "QA catalog to smartphone details smoke", "head": branch, "base": BASE_BRANCH, "body": body},
        )
        if response.status_code == 201:
            pull = _parse(response, _Pull)
            _check_pull(pull, branch, marker)
            return _receipt(pull)
        if response.status_code == 422 and (existing := await self._find_pull(branch, marker)) is not None:
            return _receipt(existing)
        raise E2EUnavailableError

    async def _ref(self, branch: str) -> _Ref:
        response = await self._request("GET", f"{REPO_API}/git/ref/heads/{branch}")
        return _parse(response, _Ref)

    async def _feature_at(self, ref: str) -> _File:
        response = await self._request("GET", f"{REPO_API}/contents/{FEATURE_PATH}", params={"ref": ref})
        if response.status_code == 404:
            raise E2EPublicationConflictError
        return _parse(response, _File)

    async def _find_pull(self, branch: str, marker: str) -> _Pull | None:
        response = await self._request(
            "GET",
            f"{REPO_API}/pulls",
            params={"head": f"{E2E_REPOSITORY.split('/')[0]}:{branch}", "base": BASE_BRANCH, "state": "all"},
        )
        if not response.is_success:
            raise E2EUnavailableError
        try:
            pulls = _PULLS.validate_json(response.content)
        except ValidationError:
            raise E2EUnavailableError from None
        if len(pulls) > 1:
            raise E2EPublicationConflictError
        if pulls:
            _check_pull(pulls[0], branch, marker)
            return pulls[0]
        return None

    async def _request(
        self, method: str, path: str, *, json: dict[str, str] | None = None, params: dict[str, str] | None = None
    ) -> Response:
        try:
            return await self._client.request(method, path, json=json, params=params)
        except RequestError:
            raise E2EUnavailableError from None


def _parse[T: BaseModel](response: Response, model: type[T]) -> T:
    if not response.is_success:
        raise E2EUnavailableError
    try:
        return model.model_validate_json(response.content)
    except ValidationError:
        raise E2EUnavailableError from None


def _check_pull(pull: _Pull, branch: str, marker: str) -> None:
    if pull.head.ref != branch or marker not in (pull.body or ""):
        raise E2EPublicationConflictError


def _receipt(pull: _Pull) -> E2EPullRequest:
    return E2EPullRequest(
        branch=pull.head.ref,
        status="pull_request",
        number=pull.number,
        url=f"https://github.com/{E2E_REPOSITORY}/pull/{pull.number}",
    )
