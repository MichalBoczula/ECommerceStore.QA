# QA service low-level design

The API is the composition root. It validates HTTP requests, authenticates the
internal caller, invokes the application service and returns Problem Details.
Application defines the repository port and orchestrates session registration
and capture. Domain owns the immutable session and exchange records.
Infrastructure owns environment settings, MongoDB documents and persistence.

The QA service owns its sessions and captures in its own MongoDB database.
Session identity is a UUID. Each exchange is stored separately, with an atomic
unique key composed of session and exchange IDs. A duplicate returns the
original record, including its timestamp, or a conflict if its content differs.
Canonical JSON keeps arbitrary upstream property names independent of BSON
document keys. The request and response are persisted together in one insert.

| Boundary | Foundation | Follow-up |
| --- | --- | --- |
| BA | Published handoff with Jira criterion and technical sources | Support more acceptance journeys |
| Knowledge Assistant | Versioned evidence from the BA handoff | Resolve additional evidence for later journeys |
| GitHub | Reviewed Gherkin proposal and E2E pull request | Expand the library of reusable Playwright steps |
| Evaluation | Immutable evidence retrieval | Compare claims with pinned sources and record review labels |

An author session fetches an approved and published BA run and checks the
selected criterion against its cited sources. The first journey renders the
catalog to phone details scenario using the checked-in E2E step vocabulary.
The proposal keeps the BA run, draft hash, criterion and source snapshot with
the rendered Gherkin in an immutable exchange.

Publication verifies the reviewed feature hash and checks the BA handoff again.
The GitHub adapter changes the managed feature on a proposal branch and opens a
PR. The feature hash identifies the branch so a retry can find the same PR.
QA stores the receipt in the session. The E2E workflow runs Playwright against
the configured test environment and saves the Playwright and Allure results.
An execute session remains available for recording execution evidence.
