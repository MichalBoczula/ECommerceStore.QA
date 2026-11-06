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
| Jira | Issue reference and capture source | Read approved criteria through a Jira adapter |
| Knowledge Assistant | Snapshot reference and capture source | Resolve and pin evidence from Azure RAG |
| Agent | Operation, model and input/output evidence | Invoke the QA agent through an application port |
| Evaluation | Immutable evidence retrieval | Compare claims with pinned sources and record review labels |

The QA worker will consume approved BA process versions and produce Playwright BDD and Allure evidence.
A registered session represents metadata for orchestration. Execution status,
queue delivery and workers will be introduced with the execution use cases.
Capture records supply evidence for evaluation. Quality labels and any training
dataset will have their own review and provenance.
