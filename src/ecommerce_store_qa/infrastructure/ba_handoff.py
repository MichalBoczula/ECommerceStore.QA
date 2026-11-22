from uuid import UUID

from httpx2 import AsyncClient, RequestError
from pydantic import ValidationError

from ecommerce_store_qa.application.e2e_models import BaHandoff, BaHandoffError, E2EUnavailableError


class BaHandoffClient:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def read(self, session_id: UUID, run_id: UUID) -> BaHandoff:
        try:
            response = await self._client.get(f"api/v1/sessions/{session_id}/runs/{run_id}/handoff")
        except RequestError:
            raise E2EUnavailableError from None
        if response.status_code in {404, 409}:
            raise BaHandoffError
        if not response.is_success:
            raise E2EUnavailableError
        try:
            return BaHandoff.model_validate_json(response.content)
        except ValidationError:
            raise BaHandoffError from None
