# ECommerceStore.QA

Foundation for authoring and executing QA scenarios from a versioned business process.

## Run locally

```sh
QA_API_KEY=local-dev-key docker compose up --build
```

Swagger is at `http://localhost:8081/swagger`. Session routes require `X-Api-Key`.
Compose creates a MongoDB volume. To run the API against an existing MongoDB,
set `QA_API_KEY`, `QA_MONGODB_URI`, and optionally `QA_MONGODB_DATABASE`
before running `uv run --locked uvicorn ecommerce_store_qa.main:app --port 8081`.

| Endpoint | Purpose |
| --- | --- |
| `GET /health/live` | Process probe |
| `GET /health/ready` | MongoDB connectivity probe |
| `POST /api/v1/sessions` | Register a session and optionally pin `jiraIssueKey` and `snapshotId` |
| `GET /api/v1/sessions/{id}` | Read session metadata |
| `PUT /api/v1/sessions/{id}/exchanges/{exchangeId}` | Record an immutable request/response pair |
| `GET /api/v1/sessions/{id}/exchanges/{exchangeId}` | Read the recorded pair |

Create a session with `{"operation":"author","jiraIssueKey":"STORE-12","snapshotId":"snapshot-1"}`.
Capture JSON with `source` (`agent`, `jira`, or `rag`), `request`, `response`
and optional `model`. Use a distinct UUID per exchange and reuse it when retrying
the same write. A different payload for the same session and exchange IDs returns
`409`. The combined canonical JSON limit is 256 KiB. Clients supply reviewed,
redacted payloads before capture. Request headers are outside the evidence contract.

## Author a storefront BDD test

The first journey opens a phone from the catalog and verifies its details.
It uses the checked-in JavaScript steps in [ECommerceStore.E2E](https://github.com/MichalBoczula/ECommerceStore.E2E).
The E2E default branch needs the starter suite before QA can publish proposals.
QA renders Gherkin from a fixed template and the published BA handoff for this journey.

| QA environment setting | Purpose |
| --- | --- |
| `QA_BA_API_URL` | Base URL of the BA API |
| `QA_BA_API_KEY` | BA API key for reading the approved handoff |
| `QA_E2E_GITHUB_TOKEN` | GitHub token with Contents and Pull requests write access scoped to `ECommerceStore.E2E` |

Create an `author` session as above. Select the criterion describing the catalog
to phone details journey in a published BA handoff for Products `GET /mobile-phones`
or `GET /mobile-phones/{id}`. `criterionIndex` is zero-based. Use a new UUID for the
proposal and reuse that UUID when retrying the same request.

```http
PUT /api/v1/sessions/{sessionId}/e2e-proposals/{proposalId}
X-Api-Key: <QA_API_KEY>
Content-Type: application/json

{"baSessionId":"<BA session UUID>","baRunId":"<BA run UUID>","criterionIndex":0}
```

Review the returned Gherkin and the criterion, source commits and snapshot under
`provenance`. Submit the returned `featureSha256` to open the pull request.

```http
PUT /api/v1/sessions/{sessionId}/e2e-proposals/{proposalId}/pull-request
X-Api-Key: <QA_API_KEY>
Content-Type: application/json

{"featureSha256":"<reviewed SHA-256>"}
```

The response contains the PR URL or the current feature URL when the same
proposal is already on `main`. GitHub Actions in E2E validates the Gherkin and
runs the browser against the test URL configured in that repository.

## Verification

Use Python from `.python-version` and uv from `pyproject.toml`.
Run `bash scripts/ci.sh` for locked install, format, lint, typing, API tests
and the wheel build. Set `TEST_MONGODB_URI` to run the database-backed restart test.
CI supplies a MongoDB service and builds the Docker image.
Pushes and manual runs on `main` publish the verified image to Docker Hub.
Use the digest in the `image-reference` artifact for deployment.

See [low-level design](docs/lld.md).
