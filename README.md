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

## Verification

Use Python from `.python-version` and uv from `pyproject.toml`.
Run `bash scripts/ci.sh` for locked install, format, lint, typing, API tests
and the wheel build. Set `TEST_MONGODB_URI` to run the database-backed restart test.
CI supplies a MongoDB service and builds the Docker image.

See [low-level design](docs/lld.md).
